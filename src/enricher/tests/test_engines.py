"""Unit tests for the swappable inference engine layer.

The open engine is exercised with a fake httpx client (no network); the two
subprocess engines with a monkeypatched subprocess.run. We assert the shared
contract: recorder-shaped JSON out, per-item latency attached, robust parsing,
and EngineError (not a crash) on backend failure.
"""

from __future__ import annotations

import json
import subprocess

import httpx
import pytest

from job_enricher.engines import (
    ClaudeCodeEngine,
    EngineError,
    OllamaEngine,
    OpenCodeEngine,
    build_engine,
)
from job_enricher.engines import claude_code as cc_mod
from job_enricher.engines import opencode_cli as oc_mod
from job_enricher.engines.base import _RETRY_NUDGE, ChunkEngine
from job_enricher.engines.prompts import (
    build_classify_prompt,
    build_judge_prompt,
    extract_json_array,
)

_CLASSIFY_JSON = json.dumps([
    {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
     "level": "mid", "level_includes": ["mid"], "tags": ["backend"],
     "locations": [], "confidence": 0.8, "reasoning": "backend role, no seniority signal"}
])
_JUDGE_JSON = json.dumps([
    {"job_listing_id": "1", "source_id": "gh", "passed": True, "confidence": 0.9,
     "needs_human": False, "notes": "ok", "reasoning": "level and category correct",
     "corrections": {}}
])

_JOB = {"job_listing_id": "1", "source_id": "gh", "title": "SWE", "company": "Acme",
        "raw_location": "SF", "clean_description": "Build backend services."}


# ---- prompt builder + extractor -------------------------------------------
def test_classify_prompt_inlines_taxonomy_and_jobs():
    p = build_classify_prompt([_JOB])
    assert "software_engineering" in p  # taxonomy rubric inlined
    assert "Build backend services." in p  # the job data
    assert "JSON array" in p


def test_judge_prompt_includes_rails():
    p = build_judge_prompt([{**_JOB, "current": {"category": "software_engineering", "level": "mid"}}])
    assert "new_grad" in p and "corrections" in p


@pytest.mark.parametrize("text,expected_len", [
    (_CLASSIFY_JSON, 1),
    ("```json\n" + _CLASSIFY_JSON + "\n```", 1),
    ("<think>reasoning here</think>\n" + _CLASSIFY_JSON, 1),
    ("Sure, here it is:\n" + _CLASSIFY_JSON + "\nDone!", 1),
    ('{"results": ' + _CLASSIFY_JSON + "}", 1),
    ("not json at all", 0),
    ("", 0),
])
def test_extract_json_array_is_robust(text, expected_len):
    assert len(extract_json_array(text)) == expected_len


# ---- OllamaEngine (fake httpx client) -------------------------------------
class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"),
                                        response=httpx.Response(self.status_code))

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, content=None, exc=None):
        self._content, self._exc, self.calls = content, exc, []

    def post(self, url, json=None):
        self.calls.append((url, json))
        if self._exc:
            raise self._exc
        return _FakeResp({"message": {"role": "assistant", "content": self._content}})


def test_ollama_classify_returns_contract_with_latency():
    eng = OllamaEngine(model="qwen3:32b", client=_FakeClient(content=_CLASSIFY_JSON))
    out = eng.classify([_JOB])
    assert len(out) == 1
    assert out[0]["category"] == "software_engineering"
    assert out[0]["job_listing_id"] == "1" and out[0]["source_id"] == "gh"
    assert isinstance(out[0]["classify_latency_ms"], int)  # latency attached


def test_ollama_judge_returns_verdict_with_latency():
    eng = OllamaEngine(model="qwen3:32b", client=_FakeClient(content=_JUDGE_JSON))
    out = eng.judge([{**_JOB, "current": {}}])
    assert out[0]["passed"] is True
    assert isinstance(out[0]["judge_latency_ms"], int)


def test_ollama_sends_structured_format_and_temperature_zero():
    fake = _FakeClient(content=_CLASSIFY_JSON)
    OllamaEngine(model="qwen3:32b", client=fake).classify([_JOB])
    _, body = fake.calls[0]
    assert body["format"] == {"type": "array", "items": {"type": "object"}}
    assert body["options"]["temperature"] == 0
    assert body["stream"] is False


def test_ollama_http_error_raises_engine_error():
    eng = OllamaEngine(model="qwen3:32b", client=_FakeClient(exc=httpx.ConnectError("down")))
    with pytest.raises(EngineError):
        eng.classify([_JOB])


def test_ollama_malformed_content_yields_empty_not_crash():
    eng = OllamaEngine(model="qwen3:32b", client=_FakeClient(content="garbage, not json"))
    assert eng.classify([_JOB]) == []


class _NonJsonBodyClient:
    """200 OK whose .json() raises ValueError (proxy HTML / truncated body)."""

    def post(self, url, json=None):
        class _R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError("Expecting value: line 1 column 1")

        return _R()


def test_ollama_non_json_body_raises_engine_error_not_valueerror():
    # Must be an EngineError so the per-chunk `except EngineError` skips it
    # instead of aborting the whole run.
    eng = OllamaEngine(model="qwen3:32b", client=_NonJsonBodyClient())
    with pytest.raises(EngineError):
        eng.classify([_JOB])


# ---- subprocess engines (monkeypatched) -----------------------------------
def _fake_completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_claude_code_parses_stream_events_array(monkeypatch):
    # Claude Code 2.x: --output-format json is an ARRAY of stream events;
    # the model text is the `result` field of the type=="result" event.
    events = json.dumps([
        {"type": "system", "subtype": "init", "tools": ["Task", "Bash"]},
        {"type": "assistant", "message": {}},
        {"type": "result", "subtype": "success", "result": _CLASSIFY_JSON},
    ])
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _fake_completed(stdout=events)

    monkeypatch.setattr(cc_mod.subprocess, "run", fake_run)
    out = ClaudeCodeEngine(model="haiku").classify([_JOB])
    assert out[0]["category"] == "software_engineering"  # NOT the tools array
    assert "--model" in captured["cmd"] and "haiku" in captured["cmd"]
    assert isinstance(out[0]["classify_latency_ms"], int)


def test_claude_code_parses_single_object_envelope(monkeypatch):
    envelope = json.dumps({"type": "result", "result": _JUDGE_JSON})
    monkeypatch.setattr(cc_mod.subprocess, "run", lambda cmd, **kw: _fake_completed(stdout=envelope))
    out = ClaudeCodeEngine(model="sonnet").judge([{**_JOB, "current": {}}])
    assert out[0]["passed"] is True


def test_claude_code_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(cc_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_completed(returncode=1, stderr="auth error"))
    with pytest.raises(EngineError):
        ClaudeCodeEngine(model="haiku").classify([_JOB])


def test_opencode_scrapes_stdout_with_think_and_fences(monkeypatch):
    noisy = "<think>let me classify</think>\nHere:\n```json\n" + _CLASSIFY_JSON + "\n```"
    monkeypatch.setattr(oc_mod.subprocess, "run", lambda cmd, **kw: _fake_completed(stdout=noisy))
    out = OpenCodeEngine(model="qwen3:32b").classify([_JOB])
    assert out[0]["level"] == "mid"


# ---- factory ---------------------------------------------------------------
def test_build_engine_dispatch():
    from job_enricher.config import settings
    assert isinstance(build_engine("claude-code", model="haiku", settings_obj=settings), ClaudeCodeEngine)
    assert isinstance(build_engine("ollama", model="qwen3:32b", settings_obj=settings), OllamaEngine)
    assert isinstance(build_engine("opencode", model="qwen3:32b", settings_obj=settings), OpenCodeEngine)


def test_build_engine_unknown_raises():
    with pytest.raises(ValueError):
        build_engine("gpt5", model="x")


# ---- ChunkEngine repair/retry (silent row-drop recovery) -------------------
class _ScriptedEngine(ChunkEngine):
    """A ChunkEngine whose `_call` returns scripted raw outputs in order and
    records every prompt it saw (mirrors _FakeClient.calls). A scripted item
    that is an Exception is raised, to exercise the EngineError paths."""

    name = "scripted"

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def _call(self, prompt):
        self.calls.append(prompt)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _arr(*objs):
    return json.dumps(list(objs))


def test_repair_stamps_position_over_echoed_ids():
    # model echoes the WRONG identity pair on a SINGLE-input chunk; the lone output
    # belongs to the lone input, so the harness stamps the known input ids back on.
    bad = _arr({"job_listing_id": "999", "source_id": "WRONG",
                "category": "software_engineering", "level": "mid"})
    eng = _ScriptedEngine([bad])
    out = eng.classify([_JOB])
    assert len(eng.calls) == 1                       # full count -> no retry
    assert out[0]["job_listing_id"] == "1"           # stamped from input, not 999
    assert out[0]["source_id"] == "gh"               # stamped from input, not WRONG
    assert out[0]["category"] == "software_engineering"   # payload preserved
    assert isinstance(out[0]["classify_latency_ms"], int)


def test_repair_retries_once_on_empty_then_recovers():
    good = _arr({"job_listing_id": "z", "source_id": "z",
                 "category": "software_engineering", "level": "mid"})
    eng = _ScriptedEngine(["", good])                # empty parse, then valid
    out = eng.classify([_JOB])
    assert len(eng.calls) == 2                        # retried exactly once
    assert _RETRY_NUDGE in eng.calls[1]               # retry carried the nudge
    assert len(out) == 1
    assert out[0]["source_id"] == "gh" and out[0]["job_listing_id"] == "1"


def test_repair_retries_on_short_batch_but_does_not_positionally_stamp():
    # batch>1: a short first parse still triggers the retry, but the recovered
    # multi-element response is NOT positionally stamped (position != identity at
    # batch>1). Id-less / mis-echoed rows keep their echoed ids so
    # record_enrichment_items' identity guard skips them downstream, rather than
    # having a real input id mis-attributed onto them.
    inputs = [
        {"job_listing_id": "1", "source_id": "gh"},
        {"job_listing_id": "2", "source_id": "gh"},
    ]
    short = _arr({"category": "software_engineering", "level": "mid"})      # 1 of 2
    full = _arr({"category": "software_engineering", "level": "mid"},
                {"category": "software_engineering", "level": "senior"})   # 2 of 2, id-less
    eng = _ScriptedEngine([short, full])
    out = eng.classify(inputs)
    assert len(eng.calls) == 2                                # short batch -> retried
    assert len(out) == 2                                      # both usable rows kept
    # no positional stamp at batch>1: the id-less rows are NOT given input ids
    assert all("job_listing_id" not in o for o in out)
    assert all("source_id" not in o for o in out)


def test_repair_no_retry_when_first_attempt_complete():
    good = _arr({"job_listing_id": "1", "source_id": "gh",
                 "category": "software_engineering", "level": "mid"})
    eng = _ScriptedEngine([good])                    # only ONE scripted reply
    out = eng.classify([_JOB])
    # a spurious retry would pop the empty script and raise IndexError
    assert len(eng.calls) == 1
    assert len(out) == 1


def test_repair_double_engine_error_reraises():
    eng = _ScriptedEngine([EngineError("boom-1"), EngineError("boom-2")])
    with pytest.raises(EngineError):
        eng.classify([_JOB])
    assert len(eng.calls) == 2                        # tried, retried, then raised


def test_repair_judge_path_stamps_and_attaches_latency():
    bad = _arr({"job_listing_id": "999", "source_id": "WRONG",
                "passed": True, "confidence": 0.9, "corrections": {}})
    eng = _ScriptedEngine([bad])
    out = eng.judge([{**_JOB, "current": {}}])
    assert out[0]["job_listing_id"] == "1" and out[0]["source_id"] == "gh"
    assert out[0]["passed"] is True
    assert isinstance(out[0]["judge_latency_ms"], int)


def test_repair_retries_on_degenerate_nondict_element():
    # a parseable-but-degenerate array ([null]) has ZERO usable rows, so the retry
    # must fire — raw len would have been 1==1 and skipped it (the [null] silent-drop
    # class, realistic on the free-form opencode path with no `format` grammar).
    good = _arr({"job_listing_id": "1", "source_id": "gh",
                 "category": "software_engineering", "level": "mid"})
    eng = _ScriptedEngine([json.dumps([None]), good])
    out = eng.classify([_JOB])
    assert len(eng.calls) == 2                        # retry fired despite len==1
    assert len(out) == 1
    assert out[0]["source_id"] == "gh" and out[0]["job_listing_id"] == "1"


def test_repair_both_attempts_degenerate_returns_empty_after_retry():
    eng = _ScriptedEngine([json.dumps([None]), json.dumps(["junk"])])
    out = eng.classify([_JOB])
    assert len(eng.calls) == 2                        # retried before giving up
    assert out == []                                  # no usable row, no crash


def test_repair_keeps_valid_echoed_ids_on_reordered_batch():
    # batch>1 (eval only): a COMPLETE but reordered response, each object echoing
    # its OWN correct id, must NOT be positionally swapped. Stamping only kicks in
    # for an echoed id that isn't a real input id.
    inputs = [
        {"job_listing_id": "1", "source_id": "gh"},
        {"job_listing_id": "2", "source_id": "gh"},
    ]
    reordered = _arr(
        {"job_listing_id": "2", "source_id": "gh", "category": "growth"},
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering"},
    )
    eng = _ScriptedEngine([reordered])
    out = eng.classify(inputs)
    assert len(eng.calls) == 1                          # complete -> no retry
    by_id = {(o["source_id"], o["job_listing_id"]): o["category"] for o in out}
    assert by_id[("gh", "1")] == "software_engineering"   # id 1 keeps ITS payload
    assert by_id[("gh", "2")] == "growth"                 # id 2 keeps ITS payload


def test_repair_preserves_partial_rows_when_retry_errors():
    # attempt 1 returns 1 of 2 usable rows; the retry backend flakes. The partial
    # row must be PRESERVED, not re-raised away (the `if not results` False branch).
    partial = _arr({"job_listing_id": "1", "source_id": "gh",
                    "category": "software_engineering", "level": "mid"})
    eng = _ScriptedEngine([partial, EngineError("retry flake")])
    inputs = [
        {"job_listing_id": "1", "source_id": "gh"},
        {"job_listing_id": "2", "source_id": "gh"},
    ]
    out = eng.classify(inputs)                          # must NOT raise
    assert len(eng.calls) == 2
    assert len(out) == 1
    assert out[0]["job_listing_id"] == "1"


def test_repair_reraises_when_first_errors_and_retry_recovers_nothing():
    # attempt 1 raises; retry returns a non-throwing EMPTY body. Nothing recovered,
    # so the original EngineError must still surface (preserve the caller's log).
    eng = _ScriptedEngine([EngineError("http 500"), ""])
    with pytest.raises(EngineError):
        eng.classify([_JOB])
    assert len(eng.calls) == 2


def test_repair_recovers_when_first_errors_and_retry_returns_usable():
    # branch-6 (the headline recovery path): attempt 1 RAISES, attempt 2 returns a
    # usable row -> the row is recovered and NO exception propagates.
    good = _arr({"job_listing_id": "z", "source_id": "z",
                 "category": "software_engineering", "level": "mid"})
    eng = _ScriptedEngine([EngineError("http 500"), good])
    out = eng.classify([_JOB])                            # must NOT raise
    assert len(eng.calls) == 2                            # errored, then retried
    assert _RETRY_NUDGE in eng.calls[1]                   # retry carried the nudge
    assert len(out) == 1
    assert out[0]["source_id"] == "gh" and out[0]["job_listing_id"] == "1"  # stamped
    assert out[0]["category"] == "software_engineering"   # payload preserved
    assert isinstance(out[0]["classify_latency_ms"], int)


def test_repair_batch1_recovers_from_wrong_id_plus_nondict_junk():
    # FIX-1 Defect A regression: batch=1 first parse is
    # [<dict w/ WRONG id>, <non-dict junk>]. Filtering the parse to dicts makes the
    # usable count 1 == len(inputs) so NO retry fires, and the single-input stamp
    # corrects the id -> the row is RECOVERED, not silently dropped downstream as
    # skipped_unknown (the exact bug this PR exists to fix, live on the ollama default).
    text = json.dumps([
        {"job_listing_id": "999", "source_id": "WRONG",
         "category": "software_engineering", "level": "mid"},
        "stray non-dict junk",
    ])
    eng = _ScriptedEngine([text])
    out = eng.classify([_JOB])
    assert len(eng.calls) == 1                            # usable==1==inputs -> no retry
    assert len(out) == 1                                  # junk dropped, dict kept
    assert out[0]["job_listing_id"] == "1"               # stamped from input, not 999
    assert out[0]["source_id"] == "gh"                   # stamped from input, not WRONG
    assert out[0]["category"] == "software_engineering"  # payload preserved


def test_repair_batch_gt1_does_not_positionally_stamp_wrong_id():
    # FIX-1 Defect B regression: at batch>1 an element echoing a WRONG id must NOT
    # be positionally stamped with a real input id (that would mis-attribute junk
    # under a real job and drop its sibling). The wrong echo is PRESERVED so the
    # downstream identity guard safely skips it — pre-change safe-skip behavior.
    inputs = [
        {"job_listing_id": "1", "source_id": "gh"},
        {"job_listing_id": "2", "source_id": "gh"},
    ]
    full = _arr(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering"},
        {"job_listing_id": "999", "source_id": "WRONG", "category": "growth"},
    )
    eng = _ScriptedEngine([full])
    out = eng.classify(inputs)
    assert len(eng.calls) == 1                            # complete count -> no retry
    by = {(o["source_id"], o["job_listing_id"]): o for o in out}
    assert ("gh", "1") in by                              # valid echo preserved
    assert ("WRONG", "999") in by                         # wrong echo NOT restamped
    assert ("gh", "2") not in by                          # never mis-attributed to input 2
