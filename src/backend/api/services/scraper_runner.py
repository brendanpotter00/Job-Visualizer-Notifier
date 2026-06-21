"""Async subprocess runner for Python scrapers."""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings

logger = logging.getLogger(__name__)

MAX_STDERR_BYTES = 10 * 1024
# Matches the first level token in a child log line. Child scripts use the
# standard %(levelname)s formatter, so this is the same anchor Python's
# logging produces. Without this, every forwarded line collapses to INFO
# and real ERRORs/Tracebacks vanish into the noise floor.
_CHILD_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")
# Grace window after process.kill() to let the stderr reader finish draining
# whatever the subprocess flushed before SIGKILL. 5s is generous; the pipe is
# closed at kill, so readline() should return EOF essentially immediately.
DRAIN_GRACE_SECONDS = 5
# After timeout, give process.wait() this long to complete the kill before
# falling through. Mirrors the prior runner's 30s post-success wait but keeps
# the timeout branch from blocking indefinitely if the kill is somehow stuck.
KILL_WAIT_SECONDS = 30


async def _stream_and_tail_stderr(
    stream: asyncio.StreamReader,
    max_bytes: int,
    line_logger: Callable[[str], None],
    tail_out: bytearray,
) -> None:
    """Stream *stream* line-by-line, mutating *tail_out* in place.

    For each line read:
      1. Append to *tail_out* (kept ≤ 2x *max_bytes* to bound memory).
      2. Decode and pass to *line_logger* — emits live progress to the
         backend logger so Railway sees per-line scraper output as it
         happens, not just on completion.

    *tail_out* is the caller-owned bytearray; even if this coroutine is
    cancelled mid-read by `asyncio.wait_for`, every line that was already
    accumulated remains in the bytearray for the timeout branch to surface.
    That's the load-bearing observability invariant — see
    docs/implementations/appleScraperHangFix/PLAN.md.
    """
    while True:
        line = await stream.readline()
        if not line:
            break
        tail_out.extend(line)
        if len(tail_out) > max_bytes * 2:
            del tail_out[:-max_bytes]
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            try:
                line_logger(text)
            except Exception:
                # Logger failure must not break the read loop, otherwise
                # one bad handler turns a healthy run into a silent hang.
                pass


def _bounded_tail_text(tail: bytearray, max_bytes: int) -> str:
    """Decode the last *max_bytes* of *tail* as utf-8."""
    if not tail:
        return ""
    return bytes(tail[-max_bytes:]).decode("utf-8", errors="replace")


@dataclass
class ScraperResult:
    exit_code: int
    output: str
    error: str
    company: str
    completed_at: str


async def run_scraper(config: Settings, company: str) -> ScraperResult:
    """Run a scraper as an async subprocess.

    Builds command: python run_scraper.py --company X --db-url Z --incremental --headless [--detail-scrape]
    Streams stderr live to the backend logger and surfaces a 10 KB tail
    of stderr in ScraperResult.error — including the timeout branch, so
    a scraper that hangs is no longer silent.
    """
    detail_flag = ["--detail-scrape"] if config.scraper_detail_scrape else []
    args = [
        config.scraper_python_path,
        f"{config.scraper_scripts_path}/run_scraper.py",
        "--company", company,
        "--db-url", config.database_url,
        "--incremental",
        "--headless",
        *detail_flag,
    ]

    # Redact --db-url value to avoid logging credentials
    safe_args = []
    skip_next = False
    for arg in args:
        if skip_next:
            safe_args.append("***REDACTED***")
            skip_next = False
        elif arg == "--db-url":
            safe_args.append(arg)
            skip_next = True
        else:
            safe_args.append(arg)
    logger.info("Running scraper: %s", " ".join(safe_args))

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            # Merge stderr into stdout (asyncio.subprocess.STDOUT is only
            # valid as the `stderr=` arg, not the `stdout=` arg) so any
            # print() output is captured alongside logger output. Combined
            # with PYTHONUNBUFFERED=1 in the Dockerfile, this gives us
            # live per-line visibility. We read from process.stdout below.
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        tail_buffer = bytearray()

        def _emit_line(text: str) -> None:
            match = _CHILD_LEVEL_RE.search(text)
            if match:
                level = getattr(logging, match.group(1))
            elif text.startswith("Traceback") or "Traceback (most recent call last)" in text:
                level = logging.ERROR
            else:
                level = logging.INFO
            logger.log(level, "scraper[%s] %s", company, text)

        # stdout is guaranteed non-None: the process is spawned with
        # stdout=PIPE (asyncio types it Optional regardless). Raise rather than
        # assert so the invariant still holds under `python -O` (which strips
        # asserts).
        if process.stdout is None:
            raise RuntimeError("scraper subprocess was spawned without a stdout pipe")
        reader_task = asyncio.create_task(
            _stream_and_tail_stderr(
                process.stdout,
                MAX_STDERR_BYTES,
                _emit_line,
                tail_buffer,
            )
        )

        timeout_seconds = config.scraper_timeout_minutes * 60
        try:
            await asyncio.wait_for(reader_task, timeout=timeout_seconds)
            await asyncio.wait_for(process.wait(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning(
                "Scraper timed out after %d minutes, killing process",
                config.scraper_timeout_minutes,
            )
            process.kill()
            kill_wait_expired = False
            try:
                await asyncio.wait_for(process.wait(), timeout=KILL_WAIT_SECONDS)
            except asyncio.TimeoutError:
                kill_wait_expired = True
                logger.error(
                    "Scraper process did not exit within %ds of SIGKILL",
                    KILL_WAIT_SECONDS,
                )
            # Drain anything the reader buffered after wait_for cancelled it.
            # CancelledError + TimeoutError are the two expected outcomes
            # (reader was cancelled by the outer wait_for; or the 5s grace
            # expired). Anything else is a real bug we want surfaced — this
            # is the file we wrote to fix a silent-failure incident, so we
            # do not silently catch unexpected exceptions here.
            try:
                await asyncio.wait_for(reader_task, timeout=DRAIN_GRACE_SECONDS)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            except Exception as drain_ex:
                logger.warning(
                    "Unexpected error draining reader_task on timeout: %r",
                    drain_ex,
                )
            tail_text = _bounded_tail_text(tail_buffer, MAX_STDERR_BYTES)
            error_message = (
                f"Process timed out after {config.scraper_timeout_minutes} minutes"
            )
            if kill_wait_expired:
                # Loud annotation in the persisted ScraperResult.error so the
                # scrape_runs row makes the zombie risk visible to operators.
                error_message = (
                    f"{error_message}\n--- WARNING: SIGKILL did not reap process within "
                    f"{KILL_WAIT_SECONDS}s; child may still be running ---"
                )
            if tail_text:
                error_message = f"{error_message}\n--- last stderr tail ---\n{tail_text}"
            return ScraperResult(
                exit_code=-2,
                output="",
                error=error_message,
                company=company,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        exit_code = process.returncode if process.returncode is not None else -3
        stderr_text = _bounded_tail_text(tail_buffer, MAX_STDERR_BYTES)
        logger.info("Scraper exited with code %d", exit_code)

        return ScraperResult(
            exit_code=exit_code,
            output="",
            error=stderr_text,
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    except (FileNotFoundError, PermissionError) as ex:
        logger.error(
            "Scraper configuration error for %s: %s: %s",
            company, type(ex).__name__, ex,
        )
        return ScraperResult(
            exit_code=-1,
            output="",
            error=f"{type(ex).__name__}: {ex}",
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as ex:
        logger.error("Unexpected failure running scraper for %s: %s", company, ex, exc_info=True)
        return ScraperResult(
            exit_code=-1,
            output="",
            error=str(ex),
            company=company,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
