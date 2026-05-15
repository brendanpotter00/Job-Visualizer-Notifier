"""Tests for the async scraper subprocess runner."""

import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import Settings
from api.services.scraper_runner import MAX_STDERR_BYTES, run_scraper


@pytest.fixture
def config():
    """Minimal Settings for scraper tests."""
    return Settings(
        database_url="postgresql://test:test@localhost/test",
        scraper_scripts_path="/fake/scripts",
        scraper_python_path="/usr/bin/python3",
        scraper_timeout_minutes=5,
        scraper_detail_scrape=False,
        scraper_companies="testco",
    )


def _make_mock_stream(data: bytes):
    """Create a mock StreamReader that yields *data* in line-sized chunks then EOF.

    The runner reads its captured-output pipe (process.stdout, with
    stderr merged in) line-by-line via `readline()` so it can emit each
    line to the live logger. To stay realistic, this helper splits
    *data* on '\\n', returning each line (with its trailing newline if
    present) on successive `readline()` calls, then `b""` for EOF. The
    legacy `read()` is also mocked to return the full payload-then-EOF
    in case any future code path falls back to it.
    """
    if data:
        # Preserve trailing newline boundaries when splitting.
        lines = data.splitlines(keepends=True)
    else:
        lines = []
    line_iter = iter(lines)

    stream = AsyncMock()

    async def _readline():
        try:
            return next(line_iter)
        except StopIteration:
            return b""

    read_returned = False

    async def _read(n=-1):
        nonlocal read_returned
        if not read_returned:
            read_returned = True
            return data
        return b""

    stream.readline = _readline
    stream.read = _read
    return stream


# Backwards-compat alias — older test names referenced this helper as
# "_make_mock_stderr" when stderr was the read pipe.
_make_mock_stderr = _make_mock_stream


def _make_mock_process(returncode=0, output=b""):
    """Build a mock process whose captured-output pipe yields *output*.

    The captured pipe is process.stdout (production code uses
    `stdout=PIPE, stderr=STDOUT` so stderr is merged into stdout). We
    attach the mock to .stdout to mirror that.
    """
    proc = AsyncMock()
    proc.stdout = _make_mock_stream(output)
    # Keep .stderr also assigned for any test that touches it directly,
    # but it's not what production reads from.
    proc.stderr = _make_mock_stream(b"")
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# -- Command construction --


class TestCommandConstruction:
    @pytest.mark.asyncio
    async def test_basic_command_args(self, config):
        mock_proc = _make_mock_process()
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
            await run_scraper(config, "google")
            args = mock_exec.call_args[0]
            assert args[0] == "/usr/bin/python3"
            assert args[1] == "/fake/scripts/run_scraper.py"
            assert "--company" in args
            idx = args.index("--company")
            assert args[idx + 1] == "google"
            assert "--env" not in args
            assert "--db-url" in args
            assert "--incremental" in args
            assert "--headless" in args
            assert "--detail-scrape" not in args

    @pytest.mark.asyncio
    async def test_detail_scrape_flag_included(self, config):
        config_detail = Settings(
            database_url="postgresql://test:test@localhost/test",
            scraper_scripts_path="/fake/scripts",
            scraper_python_path="/usr/bin/python3",
            scraper_timeout_minutes=5,
            scraper_detail_scrape=True,
            scraper_companies="testco",
        )
        mock_proc = _make_mock_process()
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
            await run_scraper(config_detail, "google")
            args = mock_exec.call_args[0]
            assert "--detail-scrape" in args

    @pytest.mark.asyncio
    async def test_real_subprocess_captures_stdout_and_stderr(self, tmp_path, config):
        """Regression test for the prod incident introduced by PR #97:
        the original "merge stdout into stderr" attempt set
        `stdout=asyncio.subprocess.STDOUT` which raises
        `ValueError: STDOUT can only be used for stderr` at
        create_subprocess_exec. The mock-based test
        `test_subprocess_merges_stderr_into_stdout` only checks the
        kwargs without exercising asyncio's actual API constraint.

        This test spawns a real Python subprocess that writes to BOTH
        stdout and stderr, then asserts both lines reach the runner's
        captured output. It would have failed loudly before the fix.
        """
        # Use a tiny one-liner Python script as the "scraper". We still
        # have to satisfy the run_scraper.py argv shape, but we only
        # need a script that emits known lines and exits cleanly.
        fake_script = tmp_path / "run_scraper.py"
        fake_script.write_text(
            "import sys\n"
            "print('STDOUT_LINE_FROM_FAKE_SCRAPER', flush=True)\n"
            "print('STDERR_LINE_FROM_FAKE_SCRAPER', file=sys.stderr, flush=True)\n"
            "sys.exit(0)\n"
        )

        real_config = Settings(
            database_url="postgresql://test:test@localhost/test",
            scraper_environment="local",
            scraper_scripts_path=str(tmp_path),
            scraper_python_path=sys.executable,
            scraper_timeout_minutes=1,
            scraper_detail_scrape=False,
            scraper_companies="testco",
        )

        result = await run_scraper(real_config, "smoke")

        assert result.exit_code == 0
        # Both pipes' content must reach the captured tail (stderr is
        # merged into stdout via stderr=STDOUT).
        assert "STDOUT_LINE_FROM_FAKE_SCRAPER" in result.error
        assert "STDERR_LINE_FROM_FAKE_SCRAPER" in result.error

    @pytest.mark.asyncio
    async def test_subprocess_merges_stderr_into_stdout(self, config):
        """The merge direction is load-bearing AND asymmetric:
        `asyncio.subprocess.STDOUT` is only valid on the `stderr=`
        argument (it means "redirect stderr into stdout"). Passing it
        as `stdout=` raises `ValueError: STDOUT can only be used for
        stderr` at create_subprocess_exec time — which is exactly the
        regression that hit prod after PR #97. Pin the *correct*
        direction so a future swap can't silently re-break it.
        """
        mock_proc = _make_mock_process()
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            await run_scraper(config, "google")
            kwargs = mock_exec.call_args.kwargs
            assert kwargs["stdout"] == asyncio.subprocess.PIPE
            assert kwargs["stderr"] == asyncio.subprocess.STDOUT


# -- Credential redaction --


class TestCredentialRedaction:
    @pytest.mark.asyncio
    async def test_db_url_not_in_log_output(self, config, caplog):
        mock_proc = _make_mock_process()
        with caplog.at_level(logging.DEBUG):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
                await run_scraper(config, "google")
        for record in caplog.records:
            assert "test:test@localhost" not in record.getMessage()

    @pytest.mark.asyncio
    async def test_redacted_placeholder_in_log(self, config, caplog):
        with caplog.at_level(logging.INFO):
            mock_proc = _make_mock_process()
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
                await run_scraper(config, "google")
        log_text = " ".join(r.getMessage() for r in caplog.records)
        assert "***REDACTED***" in log_text


# -- Successful execution --


class TestSuccessfulExecution:
    @pytest.mark.asyncio
    async def test_success_result(self, config):
        mock_proc = _make_mock_process(returncode=0, output=b"")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "google")
        assert result.exit_code == 0
        assert result.company == "google"
        assert result.output == ""
        assert result.error == ""
        assert result.completed_at

    @pytest.mark.asyncio
    async def test_stderr_truncated_to_10kb(self, config):
        # Use line-shaped data so the line-based reader emits per line and
        # tail-trims on the way through. 4096 lines × 6 bytes = 24,576 bytes
        # raw; the bounded tail keeps the last MAX_STDERR_BYTES (10 KB).
        big_stderr = b"line\n" * 5000  # 25 KB of line-shaped data
        mock_proc = _make_mock_process(returncode=1, output=big_stderr)
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "google")
        # Tail must be ≤ MAX_STDERR_BYTES; with line-aligned trimming the
        # exact size depends on where the trim cut, so allow a small slack
        # (one line's worth) below the cap.
        assert len(result.error.encode("utf-8")) <= MAX_STDERR_BYTES
        assert len(result.error.encode("utf-8")) >= MAX_STDERR_BYTES - 6

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self, config):
        mock_proc = _make_mock_process(returncode=1, output=b"crash\n")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "google")
        assert result.exit_code == 1
        assert "crash" in result.error

    @pytest.mark.asyncio
    async def test_stderr_lines_emitted_to_live_logger(self, config, caplog):
        """Each non-empty stderr line must be re-emitted to the backend
        logger as it arrives. This is the load-bearing observability
        change — it makes the scraper's per-line progress visible in
        Railway logs *during* the run, not just on completion.
        """
        mock_proc = _make_mock_process(
            returncode=0,
            output=b"Initializing browser\nScraping page 1\nFetching details 1/10: foo\n",
        )
        with caplog.at_level(logging.INFO, logger="api.services.scraper_runner"):
            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ):
                result = await run_scraper(config, "apple")

        assert result.exit_code == 0
        prefixed = [
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("scraper[apple] ")
        ]
        assert any("Initializing browser" in m for m in prefixed)
        assert any("Scraping page 1" in m for m in prefixed)
        assert any("Fetching details 1/10: foo" in m for m in prefixed)


# -- Timeout handling --


class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_timeout_returns_exit_code_minus_2(self, config):
        # Drive a real timeout: the reader_task awaits readline() forever
        # (we never return EOF) until the runner's wait_for fires.
        stream = AsyncMock()

        async def _hang_forever():
            await asyncio.sleep(3600)
            return b""

        stream.readline = _hang_forever

        mock_proc = AsyncMock()
        mock_proc.stdout = stream
        mock_proc.returncode = -9
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        config.scraper_timeout_minutes = 0.01  # 600 ms

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            result = await run_scraper(config, "google")

        assert result.exit_code == -2
        assert "timed out" in result.error.lower()
        assert result.company == "google"
        mock_proc.kill.assert_called_once()
        # process.wait is awaited inside the timeout branch (and skipped on
        # the success path that we never reach here).
        assert mock_proc.wait.await_count >= 1

    @pytest.mark.asyncio
    async def test_kill_wait_expiry_annotates_zombie_warning(self, config):
        """If `process.wait()` doesn't return within KILL_WAIT_SECONDS of
        SIGKILL, the result must surface a loud zombie warning. Without
        this, a stuck process silently looks like a clean timeout in
        scrape_runs_prod, even though the child may still be holding DB
        connections / browser PIDs.
        """
        stream = AsyncMock()

        async def _hang_forever_readline():
            await asyncio.sleep(3600)
            return b""

        stream.readline = _hang_forever_readline

        async def _wait_hangs():
            await asyncio.sleep(3600)

        mock_proc = AsyncMock()
        mock_proc.stdout = stream
        mock_proc.returncode = -9
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(side_effect=_wait_hangs)

        # Trigger the outer timeout fast, and the kill-wait timeout fast.
        config.scraper_timeout_minutes = 0.01  # 0.6 s
        with patch("api.services.scraper_runner.KILL_WAIT_SECONDS", 0.05), \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await run_scraper(config, "apple")

        assert result.exit_code == -2
        assert "WARNING: SIGKILL did not reap process" in result.error
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stderr_lines_emitted_during_read_loop(self, config):
        """Pin streaming-vs-batch: line N reaches the logger *before*
        line N+1 is read. A regression that buffered all lines and
        emitted them only after EOF would still pass the simpler
        `test_stderr_lines_emitted_to_live_logger`, because that test
        only checks "did line1 end up in caplog by the end" — which is
        true for a batch implementation too.

        Strategy: insert a 200 ms sleep *between* the readline that
        returns line1 and the readline that returns line2. In a
        streaming implementation, line1 reaches the logger right after
        readline #1, well before readline #2 finishes its sleep. In a
        batch implementation, line1 only reaches the logger after the
        whole read loop completes, i.e. after the sleep elapses.
        """
        import time

        timestamps = {}

        async def _readline():
            if "line1_returned" not in timestamps:
                timestamps["line1_returned"] = time.monotonic()
                return b"line1\n"
            if "line2_returned" not in timestamps:
                await asyncio.sleep(0.2)
                timestamps["line2_returned"] = time.monotonic()
                return b"line2\n"
            return b""

        stream = AsyncMock()
        stream.readline = _readline

        mock_proc = AsyncMock()
        mock_proc.stdout = stream
        mock_proc.returncode = 0
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        line1_logged_at: list[float] = []
        scraper_logger = logging.getLogger("api.services.scraper_runner")

        class _Latch(logging.Handler):
            def emit(self, record):
                if "scraper[apple] line1" in record.getMessage():
                    line1_logged_at.append(time.monotonic())

        latch = _Latch(level=logging.INFO)
        prev_level = scraper_logger.level
        scraper_logger.setLevel(logging.INFO)
        scraper_logger.addHandler(latch)
        try:
            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ):
                result = await run_scraper(config, "apple")
        finally:
            scraper_logger.removeHandler(latch)
            scraper_logger.setLevel(prev_level)

        assert result.exit_code == 0
        assert line1_logged_at, "line1 was never logged"
        # Streaming proof: line1 reached the logger before the readline
        # that returns line2 completed (i.e. before the 200 ms gap
        # closed). A batch implementation would fail this assertion.
        assert line1_logged_at[0] < timestamps["line2_returned"]

    @pytest.mark.asyncio
    async def test_timeout_includes_stderr_tail(self, config):
        """When the scraper hangs, the captured stderr lines must be
        surfaced in `ScraperResult.error`. Without this, the runner
        returns a hardcoded 'Process timed out' string and we have zero
        visibility into where the hang occurred — which is exactly the
        gap the Apple-90-min-hang investigation hit.
        """
        # The reader emits two lines, then blocks on readline() forever.
        # The runner's wait_for cancels it; the captured tail_buffer
        # retains the two lines for the timeout-error message.
        emitted_lines = [b"Initializing browser\n", b"Scraping page 1\n"]
        line_iter = iter(emitted_lines)

        async def _readline():
            try:
                return next(line_iter)
            except StopIteration:
                # Hang forever after emitting the lines we want surfaced.
                await asyncio.sleep(3600)
                return b""

        stream = AsyncMock()
        stream.readline = _readline

        mock_proc = AsyncMock()
        mock_proc.stdout = stream
        mock_proc.returncode = -9
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        # 1.2s — enough time for the reader to push the two queued lines
        # before the wait_for fires.
        config.scraper_timeout_minutes = 0.02

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            result = await run_scraper(config, "apple")

        assert result.exit_code == -2
        assert "timed out" in result.error.lower()
        assert "last stderr tail" in result.error.lower()
        assert "Initializing browser" in result.error
        assert "Scraping page 1" in result.error


# -- Exception fallback --


class TestExceptionFallback:
    @pytest.mark.asyncio
    async def test_file_not_found_error(self, config):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("/usr/bin/python3"),
        ):
            result = await run_scraper(config, "google")
        assert result.exit_code == -1
        assert "FileNotFoundError" in result.error

    @pytest.mark.asyncio
    async def test_permission_error(self, config):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=PermissionError("permission denied"),
        ):
            result = await run_scraper(config, "google")
        assert result.exit_code == -1
        assert "PermissionError" in result.error

    @pytest.mark.asyncio
    async def test_generic_exception(self, config):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something unexpected"),
        ):
            result = await run_scraper(config, "google")
        assert result.exit_code == -1
        assert "something unexpected" in result.error
        assert result.company == "google"
