"""Command execution helpers for the setup command."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Sequence

from sys import modules

from ._logging import logger
from ._state import BASE_ENV
from ._summary import SUMMARY

__all__ = ["_hint_for_command", "_retry", "_run"]


def _hint_for_command(cmd: Sequence[str], exit_code: int | None, stderr: str | None) -> str | None:
    joined = " ".join(map(str, cmd)).lower()
    stderr_lower = (stderr or "").lower()
    if "pip" in joined:
        if exit_code:
            if "connection" in stderr_lower or "timeout" in stderr_lower:
                return "Check connectivity or pre-download wheels with 'pip download'."
        return "Pip will reuse cached wheels from ~/.coolbox/cache/wheels when available."
    if "git" in joined:
        return "Verify git remotes or rerun with --skip-update if network access is limited."
    if "build" in joined or "wheel" in joined:
        return "Ensure build deps are installed; cached wheels will be used when builds fail."
    return None


def _resolve_run():
    setup_module = modules.get("coolbox.cli.commands.setup")
    if setup_module is not None:
        override = getattr(setup_module, "_run", None)
        if callable(override) and override is not _run:  # type: ignore[name-defined]
            return override
    return _run_impl


def _run_impl(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd_list = [str(part) for part in cmd]
    record = SUMMARY.begin_command(cmd_list, cwd=str(cwd) if cwd else None)
    final_env = dict(BASE_ENV)
    if env:
        final_env.update(env)
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd_list,
            cwd=cwd,
            env=final_env,
            timeout=timeout,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start
        hint = _hint_for_command(cmd_list, None, str(exc))
        record.finalize(exit_code=None, stderr=str(exc), duration=duration, hint=hint)
        logger.error("Command timed out: %s", " ".join(cmd_list))
        raise RuntimeError(
            f"Command '{' '.join(cmd_list)}' timed out after {timeout}s"
        ) from exc

    duration = time.perf_counter() - start
    stderr_text = result.stderr or ""
    hint = _hint_for_command(cmd_list, result.returncode, stderr_text)
    record.finalize(
        exit_code=result.returncode,
        stderr=stderr_text,
        duration=duration,
        hint=hint,
    )
    if hint and result.returncode != 0:
        logger.info("Remediation hint: %s", hint)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd_list,
            output=None,
            stderr=stderr_text,
        )
    return result


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _resolve_run()(cmd, cwd=cwd, env=env, timeout=timeout)


def _retry(
    cmd: Sequence[str],
    *,
    attempts: int = 3,
    delay: float = 0.8,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: dict | None = None,
) -> None:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _run(cmd, cwd=cwd, timeout=timeout, env=env)
            return
        except Exception as exc:  # pragma: no cover - retries hard to trigger deterministically
            last = exc
            if attempt < attempts:
                time.sleep(delay * attempt)
    if last is not None:
        raise last
