"""cutover.py — which JVN commit carries the code prod runs (PLAN §4.4 A3).

Tags ``enricher-prod-*`` first, then every commit in history; no match means
REFUSE. Built on throwaway git repos; one test checks the real tag when the
enclosing JVN checkout has it.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_cutover():
    if "cutover" in sys.modules:
        return sys.modules["cutover"]
    spec = importlib.util.spec_from_file_location("cutover", SCRIPTS / "cutover" / "cutover.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cutover"] = mod
    spec.loader.exec_module(mod)
    return mod


co = load_cutover()

GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1",
}


def g(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout.strip()


def commit_tree(repo: Path, files: dict[str, str], msg: str) -> str:
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", msg)
    return g(repo, "rev-parse", "HEAD")


@pytest.fixture
def cfg(tmp_path):
    return co.Config.from_env({"HOME": str(tmp_path / "home")})


@pytest.fixture
def jvn(tmp_path):
    """c1 (v1) -> c2 (v2, tagged enricher-prod-x) -> c3 (other dir only) -> c4 (v3).
    Plus an orphan commit (v9) reachable ONLY from tag enricher-prod-orphan."""
    repo = tmp_path / "jvn"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    c1 = commit_tree(repo, {"src/enricher/a.txt": "v1"}, "c1")
    c2 = commit_tree(repo, {"src/enricher/a.txt": "v2"}, "c2")
    g(repo, "tag", "enricher-prod-x", c2)
    g(repo, "tag", "v1.0", c1)  # not an enricher-prod-* tag: never consulted first
    c3 = commit_tree(repo, {"src/frontend/b.txt": "x"}, "c3")
    c4 = commit_tree(repo, {"src/enricher/a.txt": "v3"}, "c4")
    g(repo, "checkout", "-q", "--orphan", "lonely")
    g(repo, "rm", "-rq", "--cached", ".")
    for p in repo.glob("src"):
        import shutil
        shutil.rmtree(p)
    c9 = commit_tree(repo, {"src/enricher/a.txt": "v9"}, "c9")
    g(repo, "tag", "enricher-prod-orphan", c9)
    g(repo, "checkout", "-q", "main")
    g(repo, "branch", "-D", "lonely")
    trees = {name: g(repo, "rev-parse", f"{c}:src/enricher")
             for name, c in {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c9": c9}.items()}
    return repo, {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c9": c9}, trees


def test_the_tag_wins(cfg, jvn):
    repo, commits, trees = jvn
    m = co.derive_ref(cfg, repo, trees["c2"])
    assert (m.ref, m.commit, m.source) == ("enricher-prod-x", commits["c2"], "tag")
    assert trees["c3"] == trees["c2"]  # c3 has the same src/enricher tree; the tag still wins


def test_history_walk_finds_an_untagged_commit(cfg, jvn):
    repo, commits, trees = jvn
    m = co.derive_ref(cfg, repo, trees["c1"])
    assert (m.ref, m.commit, m.source) == (commits["c1"], commits["c1"], "history")
    m = co.derive_ref(cfg, repo, trees["c4"])
    assert m.commit == commits["c4"] and m.source == "history"


def test_a_commit_reachable_only_from_a_tag_is_found(cfg, jvn):
    """A squash-merged PR leaves the imported prod commit off main: the tag
    is what keeps it reachable."""
    repo, commits, trees = jvn
    m = co.derive_ref(cfg, repo, trees["c9"])
    assert (m.ref, m.commit) == ("enricher-prod-orphan", commits["c9"])


def test_no_matching_tree_means_refuse(cfg, jvn):
    repo, _commits, _trees = jvn
    assert co.derive_ref(cfg, repo, "0" * 40) is None


def test_works_against_a_bare_mirror(cfg, jvn, tmp_path):
    repo, commits, trees = jvn
    bare = tmp_path / "mirror.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True, env=GIT_ENV)
    assert co.derive_ref(cfg, bare, trees["c2"]).ref == "enricher-prod-x"
    assert co.derive_ref(cfg, bare, trees["c1"]).commit == commits["c1"]


def test_main_has_cutover(cfg, jvn):
    repo, _c, _t = jvn
    assert not co.main_has_cutover(cfg, repo)
    commit_tree(repo, {co.CUTOVER_PY_IN_MAIN: "# merged"}, "merge the cutover")
    assert co.main_has_cutover(cfg, repo)


def test_make_clone_is_detached_clean_owned_and_points_at_the_real_remote(cfg, jvn, tmp_path):
    repo, commits, trees = jvn
    cfg.jvn_remote_url = "https://example.invalid/JVN.git"
    dest = tmp_path / "enricher-prod"
    co.make_clone(cfg, repo, dest, commits["c2"])
    assert (dest / co.OWNED_MARKER).is_file()
    assert g(dest, "rev-parse", "HEAD") == commits["c2"]
    assert g(dest, "remote", "get-url", "origin") == "https://example.invalid/JVN.git"
    assert subprocess.run(["git", "-C", str(dest), "symbolic-ref", "-q", "HEAD"],
                          capture_output=True).returncode != 0  # detached
    (dest / ".checkout-role").write_text("prod\n")
    co.verify_clone(cfg, dest, trees["c2"])  # markers are excluded, so it is clean
    with pytest.raises(co.Refuse):
        co.verify_clone(cfg, dest, trees["c1"])


def test_make_clone_refuses_an_existing_dir(cfg, jvn, tmp_path):
    repo, commits, _t = jvn
    dest = tmp_path / "taken"
    dest.mkdir()
    with pytest.raises(FileExistsError):
        co.make_clone(cfg, repo, dest, commits["c2"])


def test_the_real_prod_tag_carries_the_live_tree(cfg):
    """The cutover's own target: tag enricher-prod-eeff1c9's src/enricher is
    tree 471165a3 (= the live prod checkout's HEAD tree when planned)."""
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        pytest.skip("not inside the JVN monorepo")
    has_tag = subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify",
                              "refs/tags/enricher-prod-eeff1c9"], capture_output=True).returncode == 0
    if not has_tag:
        pytest.skip("tag enricher-prod-eeff1c9 not fetched (CI checks out with fetch-depth 0)")
    m = co.derive_ref(cfg, root, "471165a356e7e1aab21a2b0a30f4a8a7fcb14b59")
    assert m is not None and m.ref == "enricher-prod-eeff1c9" and m.source == "tag"
    assert m.commit.startswith("3ea04981")


@pytest.mark.parametrize(
    "url, slug",
    [
        ("https://github.com/brendanpotter00/job-enricher.git", "brendanpotter00/job-enricher"),
        ("https://github.com/o/r", "o/r"),
        ("git@github.com:o/r.git", "o/r"),
        ("ssh://git@github.com/o/r.git", "o/r"),
        ("/tmp/local/job-enricher.git", None),
        ("", None),
    ],
)
def test_parse_github_slug(url, slug):
    assert co.parse_github_slug(url) == slug
