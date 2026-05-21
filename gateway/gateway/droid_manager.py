"""DroidManager — spawn and communicate with a Factory Droid (Hermes Agent).

The DroidManager wraps a persistent Hermes Agent instance that runs autonomously
on the Debian host. For V1, each user message is dispatched as an independent
`hermes chat -q` subprocess call — simple, clean, and proves the architecture.

V2 can add tmux-based persistent sessions for conversational continuity.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("gateway.droid")

# Try to find hermes in various locations
_HERMES_CANDIDATES = [
    "hermes",  # PATH
    "/home/debug/.hermes/hermes-agent/venv/bin/hermes",
    "~/.hermes/hermes-agent/venv/bin/hermes",
]


@dataclass
class DroidStatus:
    """Current status of the Factory Droid."""

    available: bool
    version: str = ""
    busy: bool = False
    error: str = ""


@dataclass
class DroidResult:
    """Result from a droid task execution."""

    success: bool
    text: str = ""
    error: str = ""
    duration_ms: int = 0


class DroidManager:
    """Manages a Factory Droid (Hermes Agent) instance.

    For V1, tasks are dispatched as `hermes chat -q` subprocess calls.
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
                        "Factory Droid available: %s (%s)",
                        candidate, version_line,
                    )
                    return
            except (FileNotFoundError, asyncio.TimeoutError, OSError):
                continue

        logger.warning("Factory Droid: hermes not found on this system")
        self._initialized = True

    async def get_status(self) -> DroidStatus:
        """Return current droid status."""
        if not self._initialized:
            await self.initialize()

        if not self._hermes_path:
            return DroidStatus(
                available=False,
                error="Hermes CLI not found on this system",
            )

        return DroidStatus(
            available=True,
            version=self._version,
            busy=self._busy,
        )

    async def send_task(
        self,
        message: str,
        timeout: float = 120.0,
    ) -> DroidResult:
        """Send a single task/prompt to the Hermes droid.

        Runs `hermes chat -q "message"` as a subprocess and returns the
        response text, stripped of status banners and session metadata.
        """
        if not self._hermes_path:
            init_ok = await self._try_discover()
            if not init_ok:
                return DroidResult(
                    success=False,
                    error="Factory Droid is not available. "
                          "Hermes CLI must be installed on the server.",
                )

        async with self._lock:
            self._busy = True

        try:
            import time
            start = time.monotonic()

            logger.info(
                "Droid task: submitting %d chars to Hermes",
                len(message),
            )

            proc = await asyncio.create_subprocess_exec(
                self._hermes_path, "chat", "-q", message, "-Q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"HERMES_YOLO_MODE": "1"},  # skip approvals
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                elapsed = int((time.monotonic() - start) * 1000)
                logger.error("Droid task timed out after %dms", elapsed)
                return DroidResult(
                    success=False,
                    error="Droid task timed out. The agent is still thinking.",
                    duration_ms=elapsed,
                )

            elapsed = int((time.monotonic() - start) * 1000)
            out_text = stdout.decode("utf-8", errors="replace")
            err_text = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.error(
                    "Droid task failed (exit=%d): %s",
                    proc.returncode, err_text[:500],
                )
                return DroidResult(
                    success=False,
                    error=f"Droid process failed (exit {proc.returncode}): "
                          f"{_clean_output(err_text)[:300]}",
                    duration_ms=elapsed,
                )

            # Strip banner lines and extract the actual response
            response = _extract_response(out_text)
            logger.info(
                "Droid task completed in %dms, %d chars of response",
                elapsed, len(response),
            )

            return DroidResult(
                success=True,
                text=response,
                duration_ms=elapsed,
            )

        except Exception as exc:
            logger.error("Droid task error: %s", exc)
            return DroidResult(
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
        logger.info("Factory Droid resources released.")


def _clean_output(text: str) -> str:
    """Remove control characters and normalize whitespace."""
    # Remove ANSI escape sequences
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    # Replace multiple whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_banners(text: str) -> str:
    """Remove hermes startup banners, warnings, and session metadata."""
    lines = text.split("\n")
    clean = []
    for line in lines:
        stripped = line.strip()
        # Skip warning banners
        if stripped.startswith("⚠"):
            continue
        if stripped.startswith("session_id:"):
            continue
        if stripped.startswith("Hermes Agent"):
            continue
        if not stripped:
            continue
        # Skip the "No text response" note from hermes -q mode
        if "no text response" in stripped.lower():
            continue
        clean.append(line)
    return "\n".join(clean).strip()


def _extract_response(raw: str) -> str:
    """Extract the droid's response text from raw hermes output."""
    # Remove ANSI escape sequences
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", raw)
    # Remove multi-line warning banners (⚠️  Normalized model...)
    text = re.sub(
        r"⚠[^\n]*(\n[ \t]*[^\n]*)?",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Remove session_id line
    text = re.sub(r"^session_id:\s*\S+\s*$", "", text, flags=re.MULTILINE)
    # Remove Hermes Agent version line
    text = re.sub(r"^Hermes Agent.*$", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    result = text.strip()
    # If after stripping we get nothing meaningful, return raw trimmed
    if not result or len(result) < 5:
        return raw.strip()
    return result
