"""HermesManager — dispatch tasks to the Hermes CLI via subprocess.

The Hermes CLI is installed on the Debian server and serves as a real
remote AI agent endpoint. Each user message is dispatched as an independent
`hermes chat -q` subprocess call.

This was originally named \"DroidManager\" but Hermes is not \"Factory Droid\"
— there is no separate \"droid\" CLI. The term \"droid\" in the Hermes ecosystem
refers to the tmux-spawning pattern for autonomous workers
(see references/droid-agent-spawning.md). The adapter is named honestly.
"""

import asyncio
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("gateway.hermes")

# Try to find hermes in various locations
_HERMES_CANDIDATES = [
    "hermes",  # PATH
    "/home/debug/.hermes/hermes-agent/venv/bin/hermes",
    "~/.hermes/hermes-agent/venv/bin/hermes",
]


@dataclass
class HermesStatus:
    """Current status of the Hermes Agent CLI."""

    available: bool
    version: str = ""
    busy: bool = False
    error: str = ""


@dataclass
class HermesResult:
    """Result from a Hermes task execution."""

    success: bool
    text: str = ""
    error: str = ""
    duration_ms: int = 0


class HermesManager:
    """Dispatches tasks to Hermes CLI.

    For V1, tasks are dispatched as `hermes chat -q` subprocess calls.
    Each call is stateless — conversation context lives in the gateway's
    session/message tables, not in the Hermes process.
    """

    def __init__(self) -> None:
        self._hermes_path: str | None = None
        self._version: str = ""
        self._busy: bool = False
        self._lock = asyncio.Lock()
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Discover hermes binary and version. Safe to call repeatedly."""
        if self._initialized:
            return

        for candidate in _HERMES_CANDIDATES:
            try:
                proc = await asyncio.create_subprocess_exec(
                    candidate, "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=10
                )
                if proc.returncode == 0:
                    version_line = stdout.decode().strip().split("\n")[0]
                    self._hermes_path = candidate
                    self._version = version_line
                    self._initialized = True
                    logger.info(
                        "Hermes Agent available: %s (%s)",
                        candidate, version_line,
                    )
                    return
            except (FileNotFoundError, asyncio.TimeoutError, OSError):
                continue

        logger.warning("Hermes CLI not found on this system")
        self._initialized = True

    async def get_status(self) -> HermesStatus:
        """Return current Hermes CLI status."""
        if not self._initialized:
            await self.initialize()

        if not self._hermes_path:
            return HermesStatus(
                available=False,
                error="Hermes CLI not found on this system",
            )

        return HermesStatus(
            available=True,
            version=self._version,
            busy=self._busy,
        )

    async def send_task(
        self,
        message: str,
        timeout: float = 120.0,
    ) -> HermesResult:
        """Send a single task/prompt to the Hermes CLI.

        Runs `hermes chat -q "message"` as a subprocess and returns the
        response text, stripped of status banners and session metadata.
        """
        if not self._hermes_path:
            init_ok = await self._try_discover()
            if not init_ok:
                return HermesResult(
                    success=False,
                    error="Hermes CLI is not available on the server.",
                )

        async with self._lock:
            self._busy = True

        try:
            import time
            start = time.monotonic()

            logger.info(
                "Hermes task: submitting %d chars",
                len(message),
            )

            proc = await asyncio.create_subprocess_exec(
                self._hermes_path, "chat", "-q", message, "-Q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"HERMES_YOLO_MODE": "1"},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                elapsed = int((time.monotonic() - start) * 1000)
                logger.error("Hermes task timed out after %dms", elapsed)
                return HermesResult(
                    success=False,
                    error="Hermes task timed out. The agent is still thinking.",
                    duration_ms=elapsed,
                )

            elapsed = int((time.monotonic() - start) * 1000)
            out_text = stdout.decode("utf-8", errors="replace")
            err_text = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.error(
                    "Hermes task failed (exit=%d): %s",
                    proc.returncode, err_text[:500],
                )
                return HermesResult(
                    success=False,
                    error=f"Hermes process failed (exit {proc.returncode}): "
                          f"{_clean_text(err_text)[:300]}",
                    duration_ms=elapsed,
                )

            response = _extract_response(out_text)
            logger.info(
                "Hermes task completed in %dms, %d chars of response, "
                "raw was %d chars",
                elapsed, len(response), len(out_text),
            )

            return HermesResult(
                success=True,
                text=response,
                duration_ms=elapsed,
            )

        except Exception as exc:
            logger.error("Hermes task error: %s", exc)
            return HermesResult(
                success=False,
                error=f"Internal error: {exc}",
            )
        finally:
            async with self._lock:
                self._busy = False

    async def _try_discover(self) -> bool:
        """Try to find hermes one more time."""
        self._initialized = False
        await self.initialize()
        return self._hermes_path is not None

    async def cleanup(self) -> None:
        """Release any held resources."""
        self._hermes_path = None
        self._version = ""
        self._busy = False
        self._initialized = False
        logger.info("Hermes Manager resources released.")


def _clean_text(text: str) -> str:
    """Remove control characters and normalize whitespace."""
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_response(raw: str) -> str:
    """Extract the response text from raw hermes output.

    Strips:
    - ANSI escape sequences
    - Warning banners (⚠ Normalized model... across multiple lines)
    - session_id lines
    - Hermes Agent version prefix lines
    - Blank lines
    """
    text = raw

    # Remove ANSI escape sequences
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)

    # Remove multi-line warning banners (⚠ Normalized model...)
    # Uses literal ⚠ (U+26A0) which matches both ⚠ and ⚠️ (with FE0F variation selector)
    text_before = text
    text = re.sub(
        r"⚠[^\n]*(\n[ \t]*[^\n]*)?",
        "",
        text,
        flags=re.MULTILINE,
    )
    if text != text_before:
        logger.info("_extract_response: stripped warning banner (%d chars removed)",
                     len(text_before) - len(text))

    # Remove session_id line
    text = re.sub(r"^session_id:\s*\S+\s*$", "", text, flags=re.MULTILINE)

    # Remove Hermes Agent version line (e.g. "Hermes Agent v0.13.0 ...")
    # NOT the response text which may also start with "Hermes"
    text = re.sub(r"^Hermes Agent\s+v?\d+\.", "", text, flags=re.MULTILINE)

    # Remove lines that are just "deepseek." or continuation of warnings
    text = re.sub(r"^[a-z]+\.\s*$", "", text, flags=re.MULTILINE)

    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    result = text.strip()

    if not result or len(result) < 5:
        logger.warning("_extract_response: stripped to near-empty, returning raw")
        return raw.strip()
    return result
