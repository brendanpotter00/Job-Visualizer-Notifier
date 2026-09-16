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
        # Every `response_schema` this fake was handed, in call order — so the
        # seam tests (and ENR-ENG-3 / ENR-PB-1) can assert the schema reaches
        # BOTH the first attempt and the retry.
        self.schemas = []

    def _call(self, prompt, *, response_schema=None):
        self.calls.append(prompt)
        self.schemas.append(response_schema)
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


# ---- ENR-ENG-1: the response_schema seam -----------------------------------
# ZERO behaviour change. `classify`/`judge` pass nothing, so their emitted bytes
# are byte-identical to before — proved by
# test_ollama_sends_structured_format_and_temperature_zero, which is UNCHANGED.

_TEST_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}}


def test_ollama_posts_a_supplied_schema_verbatim():
    fake = _FakeClient(content=_CLASSIFY_JSON)
    eng = OllamaEngine(model="qwen3:32b", client=fake)
    eng._call("hi", response_schema=_TEST_SCHEMA)
    _, body = fake.calls[0]
    assert body["format"] == _TEST_SCHEMA


def test_ollama_falls_back_to_the_permissive_schema_when_none_is_supplied():
    fake = _FakeClient(content=_CLASSIFY_JSON)
    OllamaEngine(model="qwen3:32b", client=fake)._call("hi")
    _, body = fake.calls[0]
    assert body["format"] == {"type": "array", "items": {"type": "object"}}


def test_claude_code_accepts_response_schema_and_argv_is_byte_identical(monkeypatch):
    """`claude -p` has NO structured-output flag, so the kwarg is accepted and
    IGNORED. The argv must be byte-identical with and without it — a future
    reader must not assume the constraint is enforced here."""
    seen = []
    monkeypatch.setattr(
        cc_mod.subprocess, "run",
        lambda cmd, **kw: (seen.append(list(cmd)), _fake_completed(stdout=_CLASSIFY_JSON))[1],
    )
    eng = ClaudeCodeEngine(model="haiku")
    eng._call("hi")
    eng._call("hi", response_schema=_TEST_SCHEMA)
    assert seen[0] == seen[1]


def test_opencode_accepts_response_schema_and_argv_is_byte_identical(monkeypatch):
    seen = []
    monkeypatch.setattr(
        oc_mod.subprocess, "run",
        lambda cmd, **kw: (seen.append(list(cmd)), _fake_completed(stdout=_CLASSIFY_JSON))[1],
    )
    eng = OpenCodeEngine(model="qwen3:32b")
    eng._call("hi")
    eng._call("hi", response_schema=_TEST_SCHEMA)
    assert seen[0] == seen[1]


def test_retry_attempt_receives_the_same_response_schema():
    """THE RETRY MUST CARRY THE SCHEMA. A repair attempt that dropped it would
    return unconstrained output on exactly the calls that already went wrong."""
    eng = _ScriptedEngine([_arr(), _arr({"job_listing_id": "1", "source_id": "gh"})])
    eng._call_with_repair(
        [_JOB], build_classify_prompt, "classify_latency_ms",
        response_schema=_TEST_SCHEMA,
    )
    assert len(eng.calls) == 2                     # first attempt + retry
    assert eng.schemas == [_TEST_SCHEMA, _TEST_SCHEMA]


def test_classify_and_judge_pass_no_schema():
    """The no-regression proof at the seam: the two existing lanes send None."""
    eng = _ScriptedEngine([_CLASSIFY_JSON])
    eng.classify([_JOB])
    assert eng.schemas == [None]


def test_chunk_engine_declares_a_null_subcategory_schema():
    assert ChunkEngine.subcategory_schema is None


# ---- ENR-ENG-3: the enum-constrained subcategory schema --------------------
def test_subcategory_schema_enum_is_the_sorted_frozenset_including_order():
    """THE DRIFT GUARD, and the reason the schema is BUILT rather than typed."""
    from job_enricher import taxonomy as tax
    from job_enricher.engines.ollama import _SUBCATEGORY_SCHEMA

    enum = _SUBCATEGORY_SCHEMA["items"]["properties"]["subcategories"]["items"]["enum"]
    assert enum == sorted(tax.SUBCATEGORIES)
    assert len(enum) == 17
    assert _SUBCATEGORY_SCHEMA["items"]["properties"]["subcategories"]["maxItems"] == (
        tax.MAX_SUBCATEGORIES
    )


def test_the_two_lanes_do_not_cross():
    """THE TWO-SCHEMA TEST, both halves in ONE test: a subcategory call posts the
    17-slug enum schema, and a classify call in the same file still posts the
    permissive two-key array schema."""
    from job_enricher.engines.ollama import _SUBCATEGORY_SCHEMA

    sub_fake = _FakeClient(content=_CLASSIFY_JSON)
    sub_eng = OllamaEngine(model="qwen3:32b", client=sub_fake)
    sub_eng._call("prompt", response_schema=sub_eng.subcategory_schema)
    _, sub_body = sub_fake.calls[0]
    assert sub_body["format"] == _SUBCATEGORY_SCHEMA
    assert (
        sub_body["format"]["items"]["properties"]["subcategories"]["items"]["enum"][0]
        == "ai_engineering"
    )

    cls_fake = _FakeClient(content=_CLASSIFY_JSON)
    OllamaEngine(model="qwen3:32b", client=cls_fake).classify([_JOB])
    _, cls_body = cls_fake.calls[0]
    assert cls_body["format"] == {"type": "array", "items": {"type": "object"}}


def test_subprocess_engines_declare_no_subcategory_schema():
    assert ClaudeCodeEngine(model="haiku").subcategory_schema is None
    assert OpenCodeEngine(model="qwen3:32b").subcategory_schema is None


# ---- ENR-ENG-2: the classify/judge subcategory contract + the D3 guards -----
#
# ⚠ THE LENGTH BUDGET, WITH ITS MEASURED BASELINE.
# v6 SKILL.md was 24,479 chars; the classify scaffold is ~1,729; a one-row job
# block with a 3,000-char description is ~3,205; so the v6 batch=1 prompt was
# 29,413 chars and SKILL.md was 83% of it. The compact section 1b is what v7 adds
# to that lane — NOT the full rubric, which lives in SUBCATEGORIES.md.
#
# MEASURED at 15 slugs on the committed v7 files with the fixture below: 33,619
# chars (+14.3% over v6; the rejected inline design would have been ~37,219 /
# +26.5%).
#
# RE-MEASURED after the rebase onto `main`: 39,406. TWO independent causes, and
# the bigger one is not this epic's:
#   +5,041  main's MTS work (#21) landing in SKILL.md sections 1, 2 and 6.
#     +579  the 15 -> 17 subcategory widening — two §1b table rows and two rails.
# Rounded up to the next 500 per ENR-LAT-1's rule.
#
# ⚠ A FAILURE HERE MEANS SOMEONE MOVED DETAIL BACK INTO SECTION 1b. The fix is to
# move it to SUBCATEGORIES.md, NOT to raise this constant. Raising it is correct
# ONLY when SKILL.md legitimately grew, and only after re-measuring.
_CLASSIFY_PROMPT_MAX_CHARS = 39_500

_BUDGET_FIXTURE = {
    "job_listing_id": "1", "source_id": "gh", "title": "Software Engineer",
    "company": "Acme", "raw_location": "SF", "clean_description": "x" * 3000,
}


def test_classify_prompt_carries_the_subcategory_contract():
    p = build_classify_prompt([_JOB])
    assert "subcategories" in p
    assert "subcategory_confidence" in p
    assert "full_stack is exclusive" in p
    assert "[] is a legitimate answer" in p


def test_classify_prompt_carries_all_seventeen_slugs():
    """Proves the COMPACT section 1b actually reaches the model through the
    SKILL.md inlining — if it did not, every subcategory would be a guess."""
    from job_enricher import taxonomy as tax

    p = build_classify_prompt([_JOB])
    for slug in tax.SUBCATEGORIES:
        assert slug in p, slug


def test_judge_prompt_names_subcategories_in_the_corrections_whitelist():
    """⚠ The judge STRUCTURALLY CANNOT correct a facet not named there."""
    p = build_judge_prompt([{**_JOB, "current": {}}])
    corrections = p[p.index('"corrections"'):]
    assert "subcategories" in corrections.split("<job_data>")[0]
    assert ">= 0.8" in p
    assert "not yet evaluated" in p


def test_the_detailed_rubric_is_NOT_in_either_prompt():
    """THE D3 GUARD. If SUBCATEGORIES.md's text reaches the classify or judge
    prompt, the split has evaporated and every classify + judge call pays ~8k
    chars for detail that lane does not use."""
    from job_enricher import taxonomy as tax

    rubric = tax.read_subcategory_rubric()
    # a distinctive long line from the detailed rubric only
    needle = "Silicon Validation Software Engineer"
    assert needle in rubric
    assert needle not in build_classify_prompt([_JOB])
    assert needle not in build_judge_prompt([{**_JOB, "current": {}}])
    assert rubric not in build_classify_prompt([_JOB])
    assert rubric not in build_judge_prompt([{**_JOB, "current": {}}])


def test_classify_prompt_stays_within_the_length_budget():
    assert len(build_classify_prompt([_BUDGET_FIXTURE])) <= _CLASSIFY_PROMPT_MAX_CHARS


def test_reset_taxonomy_cache_actually_clears_the_lru(tmp_path, monkeypatch):
    """⚠ `_taxonomy_text` is lru_cache(maxsize=1), so a same-process rerun after a
    SKILL.md edit silently scores the STALE rubric — the trap that would make a
    v6-vs-v7 baseline capture report a delta of zero."""
    from job_enricher import taxonomy as tax
    from job_enricher.engines import prompts as pmod

    pmod.reset_taxonomy_cache()
    before = build_classify_prompt([_JOB])
    assert "MARKER-NEW-RUBRIC" not in before

    temp = tmp_path / "SKILL.md"
    temp.write_text(tax.read_skill() + "\nMARKER-NEW-RUBRIC\n")
    monkeypatch.setattr(tax, "SKILL_PATH", temp)

    # still cached -> the OLD text
    assert "MARKER-NEW-RUBRIC" not in build_classify_prompt([_JOB])
    pmod.reset_taxonomy_cache()
    assert "MARKER-NEW-RUBRIC" in build_classify_prompt([_JOB])
    pmod.reset_taxonomy_cache()  # leave the cache clean for the next test


# ---- ENR-PB-1: the subcategory-only lane -----------------------------------
_SUB_ROWS = [
    {"job_listing_id": str(i), "source_id": "gh", "title": f"Software Engineer {i}",
     "company": "Acme", "tags": ["backend"],
     "clean_description": f"UNIQUE-DESCRIPTION-TOKEN-{i} build things"}
    for i in range(10)
]


def test_subcategory_prompt_renders_NO_description_substring():
    """⚠ THE INJECTION-BOUNDARY REGRESSION, ASSERTED IN CODE. The row dict handed
    to the model has nowhere to put `clean_description`, so the boundary is
    structural — this test is what keeps it that way."""
    from job_enricher.engines.prompts import build_subcategory_prompt

    p = build_subcategory_prompt(_SUB_ROWS)
    for row in _SUB_ROWS:
        assert row["clean_description"] not in p
        assert f"UNIQUE-DESCRIPTION-TOKEN-{row['job_listing_id']}" not in p
    # the fields it IS allowed to see are there
    assert "Software Engineer 0" in p
    assert "backend" in p


def test_the_rubric_is_amortized_not_repeated_per_row():
    """⚠ At batch 1 AND at batch 20 the rubric appears exactly once."""
    from job_enricher.engines.prompts import build_subcategory_prompt

    assert build_subcategory_prompt(_SUB_ROWS[:1]).count("<subcategory_rubric>") == 1
    assert build_subcategory_prompt(_SUB_ROWS * 2).count("<subcategory_rubric>") == 1


def test_subcategory_prompt_carries_all_seventeen_slugs_AND_the_detailed_rubric():
    """The mirror of ENR-ENG-2's 'not in classify' guard: the detailed text that
    must NOT reach the classify lane MUST reach this one."""
    from job_enricher import taxonomy as tax
    from job_enricher.engines.prompts import build_subcategory_prompt

    p = build_subcategory_prompt(_SUB_ROWS[:1])
    for slug in tax.SUBCATEGORIES:
        assert slug in p, slug
    assert "Silicon Validation Software Engineer" in p  # detailed-rubric-only text


def test_subcategory_demands_both_echoed_ids():
    from job_enricher.engines.prompts import build_subcategory_prompt

    p = build_subcategory_prompt(_SUB_ROWS[:1])
    assert "BOTH are required on EVERY object" in p


def test_subcategory_passes_the_schema_to_first_attempt_AND_retry():
    from job_enricher.engines.ollama import _SUBCATEGORY_SCHEMA

    class _WithSchema(_ScriptedEngine):
        subcategory_schema = _SUBCATEGORY_SCHEMA

    eng = _WithSchema([_arr(), _arr({"job_listing_id": "0", "source_id": "gh"})])
    eng.subcategory(_SUB_ROWS[:1])
    assert eng.schemas == [_SUBCATEGORY_SCHEMA, _SUBCATEGORY_SCHEMA]


def test_ollama_subcategory_posts_the_enum_schema_and_claude_posts_nothing_extra(
    monkeypatch,
):
    from job_enricher.engines.ollama import _SUBCATEGORY_SCHEMA

    fake = _FakeClient(content=_arr({"job_listing_id": "0", "source_id": "gh",
                                     "subcategories": ["backend"]}))
    OllamaEngine(model="qwen3:32b", client=fake).subcategory(_SUB_ROWS[:1])
    _, body = fake.calls[0]
    assert body["format"] == _SUBCATEGORY_SCHEMA

    seen = []
    monkeypatch.setattr(
        cc_mod.subprocess, "run",
        lambda cmd, **kw: (seen.append(list(cmd)),
                           _fake_completed(stdout=_arr({"job_listing_id": "0",
                                                        "source_id": "gh",
                                                        "subcategories": []})))[1],
    )
    ClaudeCodeEngine(model="haiku").subcategory(_SUB_ROWS[:1])
    assert "--output-format" in seen[0] and "format" not in seen[0]


def test_backfill_timeout_reaches_the_engine():
    from job_enricher.config import Settings

    s = Settings(engine_timeout_seconds=11.0, backfill_timeout_seconds=222.0)
    classify_engine = build_engine("claude-code", model="haiku", settings_obj=s)
    backfill_engine = build_engine(
        "claude-code", model="haiku", settings_obj=s, lane="backfill"
    )
    assert classify_engine._timeout == 11.0
    assert backfill_engine._timeout == 222.0
