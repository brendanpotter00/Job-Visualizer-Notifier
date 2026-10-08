"""``radar.py import`` and ``export_cards.py``: moving researched cards between backends.

Covers: the happy path (payloads posted verbatim under one finished run, nothing
reserved), the 409 skip, file validation (format, domain mismatch, status) before any
request, a non-409 error stopping with a partial summary, dry-run posting nothing, no
Parallel client ever constructed, and the export's row -> JSON shaping (no database).
"""

import json
from datetime import datetime, timezone

import httpx
import pytest
from launch_radar import export_cards, importer, radar
from launch_radar.backend_client import BackendClient
from launch_radar.pipeline import EXIT_ERROR, EXIT_OK, Deps
from launch_radar.state import StateStore
from tests.unit.launch_radar_fakes import FakeBackend


def _payload(domain, company=None, **over):
    p = {"company": company or domain.split(".")[0].title(), "domain": domain, "website": f"https://{domain}",
         "ats": {"provider": "ashby", "board_token": None, "verified": False, "job_count": None},
         "cost_usd": 0.29, "issues": [], "generated_at": "2026-10-07T06:56:34Z"}
    p.update(over)
    return p


def _doc(*cards):
    return {"format": importer.FORMAT, "exported_at": "2026-10-07T15:00:00Z", "source": "laptop",
            "cards": [{"domain": d, "status": s, "posted_at": "2026-10-07T06:56:34Z", "payload": _payload(d)}
                      for d, s in cards]}


def _write(tmp_path, doc):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps(doc))
    return path


class _NoParallel:
    """``make_client`` stand-in: an import must never construct a Parallel client."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("import constructed a Parallel client")


def _deps(tmp_path, transport, logs, make_client=None):
    return Deps(backend=BackendClient("http://backend.test", "k", transport=transport),
                make_client=make_client or _NoParallel(), store=StateStore(tmp_path / "state"),
                log=logs.append, host="server-laptop")


def _posted_cards(fb):
    return [json.loads(r.content)["payload"] for r in fb.requests
            if r.method == "POST" and r.url.path.endswith("/cards")]


def test_import_posts_every_payload_verbatim_under_one_finished_run(tmp_path):
    fb, logs, no_parallel = FakeBackend(), [], _NoParallel()
    doc = _doc(("alpha.ai", "new"), ("beta.io", "saved"), ("gamma.dev", "archived"))
    rc = radar.main(["import", "--file", str(_write(tmp_path, doc))],
                    deps=_deps(tmp_path, fb.transport(), logs, no_parallel))
    assert rc == EXIT_OK
    assert _posted_cards(fb) == [c["payload"] for c in doc["cards"]]  # untouched, in file order
    assert set(fb.cards) == {"alpha.ai", "beta.io", "gamma.dev"}
    assert all(row["status"] == "new" for row in fb.cards.values())  # the internal API only creates new
    (run,) = fb.runs.values()
    assert run["status"] == "ok" and run["cards_posted"] == 3 and run["host"] == "server-laptop"
    assert run["budget"] == importer.IMPORT_RUN_BUDGET_USD
    assert fb.spend == [] and no_parallel.calls == 0  # nothing reserved, no research
    text = "\n".join(logs)
    assert "import summary: imported 3 · skipped as duplicate 0 · failed 0 · of 3 in the file" in text
    # the saved / archived cards are listed for the admin to re-apply
    assert "saved    beta.io (Beta)" in text and "archived gamma.dev (Gamma)" in text
    assert "new      alpha.ai" not in text


def test_import_skips_a_409_duplicate_and_rerun_is_a_no_op(tmp_path):
    fb, logs = FakeBackend(), []
    fb.cards["alpha.ai"] = {"id": 99, "status": "archived", "payload": _payload("alpha.ai"),
                            "tracked_company_id": None}
    path = _write(tmp_path, _doc(("alpha.ai", "new"), ("beta.io", "new")))
    assert radar.main(["import", "--file", str(path)], deps=_deps(tmp_path, fb.transport(), logs)) == EXIT_OK
    assert fb.cards["alpha.ai"]["id"] == 99 and "beta.io" in fb.cards
    assert "import summary: imported 1 · skipped as duplicate 1 · failed 0 · of 2 in the file" in logs[-1]

    logs.clear()
    assert radar.main(["import", "--file", str(path)], deps=_deps(tmp_path, fb.transport(), logs)) == EXIT_OK
    assert "import summary: imported 0 · skipped as duplicate 2 · failed 0 · of 2 in the file" in logs[-1]
    assert [r["status"] for r in fb.runs.values()] == ["ok", "ok"] and fb.spend == []


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(format="launch-radar-cards/v2"), "format must be 'launch-radar-cards/v1'"),
    (lambda d: d.pop("format"), "format must be"),
    (lambda d: d.update(cards={"alpha.ai": {}}), "'cards' must be a list"),
    (lambda d: d["cards"][1]["payload"].update(domain="evil.com"),
     "card 1 (beta.io): payload domain 'evil.com' does not match the card's domain"),
    (lambda d: d["cards"][1]["payload"].pop("domain"), "card 1 (beta.io): payload domain 'None' does not match"),
    (lambda d: d["cards"][0].update(payload="{}"), "card 0 (alpha.ai): payload must be an object"),
    (lambda d: d["cards"][0].update(domain="https://www.Alpha.ai/x"), "is not a normalized domain"),
    (lambda d: d["cards"][0].update(status="deleted"), "status must be one of new, saved, archived"),
    (lambda d: d["cards"].append(dict(d["cards"][0])), "card 2 (alpha.ai): duplicate domain"),
    (lambda d: d["cards"][0]["payload"].update(company=""), "payload company must be a non-empty string"),
])
def test_a_bad_file_is_rejected_before_any_request(tmp_path, capsys, mutate, message):
    fb, logs = FakeBackend(), []
    doc = _doc(("alpha.ai", "new"), ("beta.io", "new"))
    mutate(doc)
    rc = radar.main(["import", "--file", str(_write(tmp_path, doc))], deps=_deps(tmp_path, fb.transport(), logs))
    assert rc == EXIT_ERROR
    assert message in capsys.readouterr().err
    assert fb.requests == [] and fb.runs == {}  # nothing posted, no run opened


@pytest.mark.parametrize("content", ["not json {", "[1, 2]", "\udcff"])
def test_unreadable_or_non_object_files_are_rejected(tmp_path, capsys, content):
    path = tmp_path / "cards.json"
    path.write_bytes(content.encode("utf-8", "surrogateescape"))
    fb = FakeBackend()
    assert radar.main(["import", "--file", str(path)], deps=_deps(tmp_path, fb.transport(), [])) == EXIT_ERROR
    assert capsys.readouterr().err.startswith("import: ") and fb.requests == []


def test_missing_file_is_reported(tmp_path, capsys):
    fb = FakeBackend()
    rc = radar.main(["import", "--file", str(tmp_path / "nope.json")], deps=_deps(tmp_path, fb.transport(), []))
    assert rc == EXIT_ERROR and "cannot read" in capsys.readouterr().err and fb.requests == []


def test_a_non_409_error_stops_with_a_partial_summary(tmp_path):
    fb, logs = FakeBackend(), []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/cards") and \
                json.loads(request.content)["payload"]["domain"] == "beta.io":
            return httpx.Response(422, json={"detail": [{"loc": ["body", "payload", "leaders"], "msg": "bad"}]})
        return fb.handle(request)

    fb.cards["gamma.dev"] = {"id": 7, "status": "new", "payload": _payload("gamma.dev"),
                             "tracked_company_id": None}
    doc = _doc(("alpha.ai", "new"), ("gamma.dev", "new"), ("beta.io", "saved"), ("delta.co", "new"))
    rc = radar.main(["import", "--file", str(_write(tmp_path, doc))],
                    deps=_deps(tmp_path, httpx.MockTransport(handler), logs))
    assert rc == EXIT_ERROR
    assert set(fb.cards) == {"alpha.ai", "gamma.dev"}  # stopped at beta.io; delta.co never attempted
    assert [d["domain"] for d in _posted_cards(fb)] == ["alpha.ai", "gamma.dev"]
    (run,) = fb.runs.values()
    assert run["status"] == "error" and run["cards_posted"] == 1 and "422" in run["notes"]
    text = "\n".join(logs)
    assert "import: stopped at beta.io: BackendError: POST /cards -> 422" in text
    assert logs[-1].startswith("import summary: imported 1 · skipped as duplicate 1 · failed 1 (beta.io) · "
                               "not attempted 1 · of 4 in the file")
    assert "saved    beta.io" not in text  # not on the backend, so nothing to re-apply


def test_a_dropped_connection_mid_import_stops_and_says_rerun_is_safe(tmp_path):
    fb, logs = FakeBackend(), []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/cards") and \
                json.loads(request.content)["payload"]["domain"] == "beta.io":
            raise httpx.ReadTimeout("timed out", request=request)
        return fb.handle(request)

    rc = radar.main(["import", "--file", str(_write(tmp_path, _doc(("alpha.ai", "new"), ("beta.io", "new"))))],
                    deps=_deps(tmp_path, httpx.MockTransport(handler), logs))
    assert rc == EXIT_ERROR
    text = "\n".join(logs)
    assert "import: stopped at beta.io: ReadTimeout" in text and "re-running is safe" in text
    assert "imported 1 · skipped as duplicate 0 · failed 1 (beta.io)" in logs[-1]
    assert [r["status"] for r in fb.runs.values()] == ["error"]


def test_a_failed_run_start_posts_nothing(tmp_path):
    logs = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid or missing internal API key"})

    rc = radar.main(["import", "--file", str(_write(tmp_path, _doc(("alpha.ai", "new"))))],
                    deps=_deps(tmp_path, httpx.MockTransport(handler), logs))
    assert rc == EXIT_ERROR
    assert "import: stopped before posting any card: BackendError: POST /runs -> 401" in "\n".join(logs)
    assert "imported 0 · skipped as duplicate 0 · failed 0 · not attempted 1" in logs[-1]


def test_dry_run_reads_seen_and_posts_nothing(tmp_path):
    fb, logs, no_parallel = FakeBackend(), [], _NoParallel()
    fb.cards["alpha.ai"] = {"id": 1, "status": "new", "payload": _payload("alpha.ai"),
                            "tracked_company_id": None}
    path = _write(tmp_path, _doc(("alpha.ai", "new"), ("beta.io", "saved")))
    rc = radar.main(["import", "--file", str(path), "--dry-run"],
                    deps=_deps(tmp_path, fb.transport(), logs, no_parallel))
    assert rc == EXIT_OK
    assert [r.method for r in fb.requests] == ["GET"] and fb.runs == {} and set(fb.cards) == {"alpha.ai"}
    assert no_parallel.calls == 0
    text = "\n".join(logs)
    assert "would skip alpha.ai" in text and "would import beta.io (Beta) [saved]" in text
    assert "would import 1, would skip 1 already on the backend; nothing posted" in logs[-1]


def test_import_needs_no_parallel_key(monkeypatch, tmp_path, capsys):
    """Through the real config path: only BACKEND_URL (+ the internal key off loopback) is required."""
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    path = _write(tmp_path, _doc(("alpha.ai", "new")))
    assert radar.main(["import", "--file", str(path)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "INTERNAL_API_KEY is not set" in err and "PARALLEL_API_KEY" not in err


# ---- export_cards.py --------------------------------------------------------------------
def test_export_and_import_agree_on_the_format_tag():
    assert export_cards.FORMAT == importer.FORMAT == "launch-radar-cards/v1"


def test_shape_export_sorts_by_posted_at_and_drops_tombstones():
    t = lambda h: datetime(2026, 10, 7, h, 0, 0, tzinfo=timezone.utc)  # noqa: E731
    rows = [
        {"domain": "late.ai", "status": "saved", "posted_at": t(14), "payload": _payload("late.ai")},
        {"domain": "gone.io", "status": "deleted", "posted_at": t(5), "payload": None},
        {"domain": "early.dev", "status": "new", "posted_at": t(6), "payload": _payload("early.dev")},
    ]
    doc = export_cards.shape_export(rows, exported_at=datetime(2026, 10, 7, 15, 30, tzinfo=timezone.utc),
                                    source="laptop.local")
    assert doc == {
        "format": "launch-radar-cards/v1", "exported_at": "2026-10-07T15:30:00Z", "source": "laptop.local",
        "cards": [
            {"domain": "early.dev", "status": "new", "posted_at": "2026-10-07T06:00:00Z",
             "payload": _payload("early.dev")},
            {"domain": "late.ai", "status": "saved", "posted_at": "2026-10-07T14:00:00Z",
             "payload": _payload("late.ai")},
        ],
    }
    assert export_cards.summary(doc) == "2 card(s) (new 1, saved 1)"
    # what the export writes, the import accepts
    parsed = importer.parse_export(json.loads(json.dumps(doc)))
    assert [(c.domain, c.status) for c in parsed.cards] == [("early.dev", "new"), ("late.ai", "saved")]
    assert parsed.source == "laptop.local"


def test_shape_export_refuses_a_live_row_without_a_payload():
    with pytest.raises(ValueError, match="no payload object"):
        export_cards.shape_export([{"domain": "a.ai", "status": "new", "posted_at": None, "payload": None}],
                                  exported_at=datetime.now(timezone.utc), source="x")


def test_export_writes_a_neutral_source_label_never_the_hostname(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: "Someones-MacBook-Pro.local")
    rows = [{"domain": "early.dev", "status": "new", "posted_at": datetime(2026, 10, 7, 6, tzinfo=timezone.utc),
             "payload": _payload("early.dev")}]
    monkeypatch.setattr(export_cards, "fetch_rows", lambda url: rows)
    out = tmp_path / "cards.json"
    assert export_cards.main(["--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert json.loads(text)["source"] == "local" and "MacBook" not in text
    assert export_cards.main(["--out", str(out), "--source", "server-laptop"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["source"] == "server-laptop"
    for bad in ("", "has space", "a/b", "x" * 65):
        with pytest.raises(SystemExit):
            export_cards.main(["--out", str(out), "--source", bad])


def test_export_never_prints_the_database_password():
    url = "postgresql+psycopg2://admin:s3cr3t@db.internal:6543/jvn_launch_radar"
    assert export_cards.db_label(url) == "db.internal:6543/jvn_launch_radar"
    assert export_cards.libpq_url(url) == "postgresql://admin:s3cr3t@db.internal:6543/jvn_launch_radar"
    assert export_cards.redact("auth failed for s3cr3t", url) == "auth failed for ***"
    assert export_cards.default_out(datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc)).name == "cards-2026-10-07.json"
