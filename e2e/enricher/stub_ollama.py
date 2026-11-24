"""A deterministic stand-in for ollama's native ``POST /api/chat``.

The enricher's prod engine (``engines/ollama.py``) is a plain HTTP client: it
posts ``{"model", "messages": [{"role": "user", "content": <prompt>}], "stream":
false, "format": <json schema>, "options": {"temperature": 0}}`` and reads
``message.content`` back. Pointing ``OLLAMA_BASE_URL`` at this server therefore
runs the enricher's REAL engine code path — prompt build, HTTP, envelope parse,
JSON-array recovery, the retry nudge, single-input identity repair — with only
the weights replaced. $0, and nothing leaves the machine.

How it answers
--------------
It finds the LAST ``<job_data>`` block in the prompt (the rubric above it may
mention the tag), parses the JSON array inside, and answers each element from
``fixtures.py``. It tells the three prompts apart by their opening line:

* ``You are a job-classification agent``     -> classify
* ``You are an adversarial quality judge``   -> judge
* ``You are a software-engineering SUBCATEGORY agent`` -> subcategory (backfill lane)

Both the v6 tag's and main's v7 prompts start with those lines, and the answer
always carries the v7 keys too — the v6 recorder ignores keys it does not read.

Control endpoints (loopback only; the server binds 127.0.0.1)
-------------------------------------------------------------
``POST /__stub/mode``  ``{"mode": <mode>, "slow_s": N, "stage": "classify"|"judge"|"subcategory"|"all"}``
    normal | http500 | garbage | hallucinate_id | invalid_facet | slow
``GET  /__stub/requests``  every request this server answered since the last reset
``POST /__stub/reset``     clear the log, back to ``normal``

A global mode applies to the stages ``stage`` names (default ``all``); when it
does not apply, per-row ``Job.behaviour`` (classify only) decides.

Run: ``python e2e/enricher/stub_ollama.py --port 8215``. It refuses ``:11434``
(the real ollama — prod's) and any non-loopback bind.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import fixtures  # noqa: E402

REAL_OLLAMA_PORT = 11434
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
MODES = ("normal", "http500", "garbage", "hallucinate_id", "invalid_facet", "slow")
STAGES = ("all", "classify", "judge", "subcategory")

_STAGE_MARKERS = (
    ("You are a job-classification agent", "classify"),
    ("You are an adversarial quality judge", "judge"),
    ("You are a software-engineering SUBCATEGORY agent", "subcategory"),
)


#: Sentinel result: answer with a valid envelope whose content is prose.
_GARBLED = object()


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mode = "normal"
        self.stage = "all"
        self.slow_s = 0.0
        self.requests: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self.lock:
            self.mode, self.stage, self.slow_s = "normal", "all", 0.0
            self.requests = []


STATE = _State()


def detect_stage(prompt: str) -> str | None:
    for marker, stage in _STAGE_MARKERS:
        if marker in prompt:
            return stage
    return None


def extract_job_data(prompt: str) -> list[dict[str, Any]]:
    """The JSON array inside the LAST ``<job_data>`` ... ``</job_data>`` block."""
    start = prompt.rfind("<job_data>")
    if start == -1:
        raise ValueError("prompt has no <job_data> block")
    end = prompt.find("</job_data>", start)
    if end == -1:
        raise ValueError("unterminated <job_data> block")
    payload = json.loads(prompt[start + len("<job_data>"):end].strip())
    if not isinstance(payload, list):
        raise ValueError("<job_data> is not a JSON array")
    return [p for p in payload if isinstance(p, dict)]


def _answers(stage: str, items: list[dict[str, Any]], mode: str) -> tuple[int, str | None, Any]:
    """(http_status, raw_body_override, results). A raw body means "send this
    text verbatim, not an ollama envelope"."""
    if mode == "http500":
        return 500, json.dumps({"error": "e2e stub: http500 mode"}), None
    if mode == "garbage":
        return 200, "<html><body>502 Bad Gateway (e2e stub garbage)</body></html>", None

    if stage == "judge":
        return 200, None, [fixtures.judge_answer(i) for i in items]
    if stage == "subcategory":
        return 200, None, [fixtures.subcategory_answer(i) for i in items]

    # classify
    results: list[Any] = []
    for item in items:
        job = fixtures.job_for(item)
        if mode == "invalid_facet":
            results.append(fixtures.classify_answer(item, category_override="astronaut_engineering"))
            continue
        if mode == "hallucinate_id":
            results.append(fixtures.classify_answer(item))
            ghost = dict(fixtures.classify_answer(item))
            ghost["job_listing_id"] = fixtures.GHOST_PREFIX + str(item.get("job_listing_id"))
            results.append(ghost)
            continue
        behaviour = job.behaviour
        if behaviour == "http_garbage":
            return 200, "<html><body>upstream proxy error (e2e stub)</body></html>", None
        if behaviour == "garbled":
            # A valid envelope whose CONTENT is prose: the engine's JSON recovery
            # yields [] and the row records nothing this tick.
            return 200, None, _GARBLED
        results.append(fixtures.classify_answer(item))
        if behaviour == "extra_ghost":
            ghost = dict(fixtures.classify_answer(item))
            ghost["job_listing_id"] = fixtures.GHOST_PREFIX + str(item.get("job_listing_id"))
            results.append(ghost)
    return 200, None, results


class Handler(BaseHTTPRequestHandler):
    server_version = "e2e-stub-ollama/1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401 - quiet stdlib logger
        sys.stderr.write("stub: " + (fmt % args) + "\n")

    # --- helpers -----------------------------------------------------------
    def _send(self, status: int, body: str, ctype: str = "application/json") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> Any:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _record(self, entry: dict[str, Any]) -> None:
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
        entry.setdefault("path", self.path)
        entry.setdefault("method", self.command)
        entry.setdefault("host", self.headers.get("Host"))
        with STATE.lock:
            STATE.requests.append(entry)

    # --- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path == "/__stub/requests":
            with STATE.lock:
                reqs = list(STATE.requests)
                body = {
                    "mode": STATE.mode, "stage": STATE.stage, "slow_s": STATE.slow_s,
                    "count": len(reqs),
                    "chat_count": sum(1 for r in reqs if r.get("path") == "/api/chat"),
                    "requests": reqs,
                }
            self._send(200, json.dumps(body))
            return
        self._record({"status": 404})
        self._send(404, json.dumps({"error": f"e2e stub: no GET {self.path}"}))

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/__stub/reset":
            STATE.reset()
            self._send(200, json.dumps({"ok": True}))
            return
        if self.path == "/__stub/mode":
            body = self._read_json()
            mode = body.get("mode", "normal")
            stage = body.get("stage", "all")
            if mode not in MODES or stage not in STAGES:
                self._send(400, json.dumps({"error": f"mode must be one of {MODES}, stage one of {STAGES}"}))
                return
            with STATE.lock:
                STATE.mode, STATE.stage = mode, stage
                STATE.slow_s = float(body.get("slow_s") or 0.0)
            self._send(200, json.dumps({"ok": True, "mode": mode, "stage": stage}))
            return
        if self.path != "/api/chat":
            self._record({"status": 404})
            self._send(404, json.dumps({"error": f"e2e stub: no POST {self.path}"}))
            return
        self._chat()

    def _chat(self) -> None:
        try:
            body = self._read_json()
            messages = body.get("messages") or []
            prompt = messages[-1]["content"] if messages else ""
            stage = detect_stage(prompt)
            items = extract_job_data(prompt)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self._record({"status": 400, "error": str(exc)})
            self._send(400, json.dumps({"error": f"e2e stub: unreadable chat request: {exc}"}))
            return
        if stage is None:
            self._record({"status": 400, "error": "unknown prompt"})
            self._send(400, json.dumps({"error": "e2e stub: prompt matched no known stage"}))
            return

        with STATE.lock:
            g_mode, g_stage, slow_s = STATE.mode, STATE.stage, STATE.slow_s
        applies = g_stage in ("all", stage)
        mode = g_mode if applies else "normal"
        if mode == "slow":
            time.sleep(max(slow_s, 0.0))
            mode = "normal"

        fmt = body.get("format")
        options = body.get("options") or {}
        entry = {
            "stage": stage,
            "model": body.get("model"),
            "stream": body.get("stream"),
            "temperature": options.get("temperature"),
            "format_type": fmt.get("type") if isinstance(fmt, dict) else None,
            "job_ids": [i.get("job_listing_id") for i in items],
            "source_ids": [i.get("source_id") for i in items],
            "retry_nudge": "IMPORTANT: return EXACTLY one JSON object per input job" in prompt,
            "mode": g_mode if applies else "normal",
        }
        status, raw, results = _answers(stage, items, mode)
        entry["status"] = status
        self._record(entry)
        if raw is not None:
            self._send(status, raw, "application/json" if status != 200 else "text/html")
            return
        if results is _GARBLED:
            content = "I'm sorry, I can't classify this posting right now."
        else:
            content = json.dumps(results)
        envelope = {
            "model": body.get("model"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {"role": "assistant", "content": content},
            "done": True,
        }
        self._send(200, json.dumps(envelope))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8215)
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK_HOSTS:
        print(f"stub_ollama: refusing non-loopback bind {args.host!r}", file=sys.stderr)
        return 2
    if args.port == REAL_OLLAMA_PORT:
        print("stub_ollama: refusing :11434 — that is the REAL ollama prod uses", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"stub_ollama: listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
