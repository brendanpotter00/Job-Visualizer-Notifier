"""Prove the replay-side safety invariants the spike claims. No network.

Run: .venv/bin/python test_invariants.py
"""

from __future__ import annotations

import json
import sys

import replay
from recipe_schema import RecipeError, validate_recipe

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


def expect_raises(name: str, fn, expected_substring: str = "") -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - asserting on failure is the point
        message = str(exc)
        ok = expected_substring.lower() in message.lower() if expected_substring else True
        check(name, ok, f"raised {type(exc).__name__}: {message[:90]}")
    else:
        check(name, False, "did NOT raise — this invariant is broken")


BASE = {
    "recipe_version": 1,
    "kind": "http_json",
    "entrypoint": {"method": "GET", "url": "https://example.com/j.json"},
    "records_path": "jobs",
    "fields": {"id": "id", "title": "title", "url": "url"},
    "expected_min_jobs": 10,
}


def main() -> None:
    # 1. The core contract: a partial harvest is a failure, not a result.
    expect_raises(
        "incomplete harvest raises (got 10 of declared 4000)",
        lambda: replay.check_completeness({**BASE, "total_path": "hits"}, {"hits": 4000}, 10),
        "incomplete harvest",
    )
    check(
        "complete harvest passes (got 76 of declared 76)",
        replay.check_completeness({**BASE, "total_path": "hits"}, {"hits": 76}, 76) is None,
    )
    check(
        "within tolerance passes (got 98 of declared 100, 5% allowed)",
        replay.check_completeness({**BASE, "total_path": "hits"}, {"hits": 100}, 98) is None,
    )
    expect_raises(
        "vanished completeness oracle raises rather than passing silently",
        lambda: replay.check_completeness({**BASE, "total_path": "hits"}, {"renamed": 76}, 76),
        "did not resolve",
    )

    # 2. Zero records must never be reported as "no jobs today".
    expect_raises(
        "zero records raises, never returns []",
        lambda: replay.run_recipe({**BASE, "kind": "http_json", "entrypoint": {"method": "GET", "url": "https://example.com/x"}, "records_path": "jobs"})
        if False else _run_with_records([]),
        "zero records",
    )

    # 3. A count below the floor raises.
    expect_raises(
        "count below expected_min_jobs raises",
        lambda: _run_with_records([{"id": i, "title": "t", "url": "u"} for i in range(3)]),
        "below expected_min_jobs",
    )

    # 4. The agent-free guarantee.
    check(
        "no agent/LLM module reachable on the replay path",
        replay.assert_no_agent_imports() is None,
        f"forbidden={replay.FORBIDDEN_MODULES}",
    )
    sys.modules["anthropic"] = object()  # simulate a leak
    expect_raises(
        "import guard fires if an LLM client ever leaks in",
        replay.assert_no_agent_imports,
        "never import an agent",
    )
    del sys.modules["anthropic"]

    # 5. Schema validation rejects malformed recipes loudly.
    expect_raises(
        "recipe missing required field is rejected",
        lambda: validate_recipe({**BASE, "fields": {"title": "t"}}),
        "fields.id",
    )
    expect_raises(
        "non-https entrypoint is rejected",
        lambda: validate_recipe({**BASE, "entrypoint": {"method": "GET", "url": "http://insecure.example/j"}}),
        "https",
    )

    width = max(len(name) for _, name, _ in results) + 2
    for status, name, detail in results:
        print(f"[{status}] {name:<{width}} {detail}")
    failures = sum(1 for status, _, _ in results if status == FAIL)
    print(f"\n{len(results) - failures}/{len(results)} invariants hold")
    sys.exit(1 if failures else 0)


def _run_with_records(records: list[dict]) -> list[dict]:
    """Drive run_recipe against a stubbed transport returning `records`."""
    import httpx

    payload = json.dumps({"jobs": records})
    original = replay.httpx.Client

    class StubClient(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(
                lambda request: httpx.Response(200, text=payload, request=request)
            )
            super().__init__(*args, **kwargs)

    replay.httpx.Client = StubClient
    try:
        return replay.run_recipe(dict(BASE))
    finally:
        replay.httpx.Client = original


if __name__ == "__main__":
    main()
