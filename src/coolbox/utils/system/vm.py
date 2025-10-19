#!/usr/bin/env python3
"""
VM/debug launcher that is Windows-safe.

Rules
- Never exec *.sh on Windows. Use PowerShell (.ps1) or WSL bash.
- Prefer Docker/Podman/Vagrant if explicitly requested and available.
- Otherwise fall back to a local debugpy session.
- Idempotent. No WinError 193 from CreateProcess.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping, Optional

from coolbox.paths import dev_scripts_dir, project_root, python_scripts_dir, scripts_dir

logger = logging.getLogger(__name__)
ROOT = project_root()
SCRIPTS = scripts_dir()
PYTHON_SCRIPTS = python_scripts_dir()
DEV_SCRIPTS = dev_scripts_dir()


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _exists(p: Path) -> bool:
    try:
        return p.exists()
    except Exception:
        return False


def _which(name: str) -> str | None:
    return shutil.which(name)


def available_backends() -> list[str]:
    """Return a list of installed VM backends."""
    return [name for name in ("docker", "podman", "vagrant") if _which(name)]


def _env_with_port(port: int, base: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env["DEBUG_PORT"] = str(port)
    return env


def _spawn(cmd: Iterable[str], *, env: Optional[Mapping[str, str]] = None, cwd: Optional[Path] = None) -> None:
    """Non-blocking spawn with inherited stdio."""
    logger.info("Launching: %s", " ".join(cmd))
    subprocess.Popen(list(cmd), env=None if env is None else dict(env), cwd=str(cwd) if cwd else None)


def _is_windows() -> bool:
    return os.name == "nt"


def _powershell_exe() -> str:
    # Avoid PATH surprises
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    ps = Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(ps) if ps.exists() else "powershell"


def _wsl_available() -> bool:
    return _which("wsl.exe") is not None


# --------------------------------------------------------------------------------------
# strategies
# --------------------------------------------------------------------------------------
def _launch_docker(port: int, env: Optional[Mapping[str, str]] = None) -> bool:
    exe = _which("docker") or _which("podman")
    if not exe:
        return False
    compose = DEV_SCRIPTS / "run_devcontainer.sh"
    if _is_windows():
        # Windows cannot exec .sh; use WSL if present
        if not _wsl_available() or not _exists(compose):
            return False
        _spawn([
            "wsl.exe",
            "bash",
            "-lc",
            f"cd '{ROOT.as_posix()}' && ./scripts/dev/run_devcontainer.sh",
        ], env=_env_with_port(port, env))
        return True
    # POSIX
    if _exists(compose):
        _spawn(["bash", str(compose)], env=_env_with_port(port, env))
        return True
    return False


def _launch_vagrant(port: int, env: Optional[Mapping[str, str]] = None) -> bool:
    exe = _which("vagrant")
    if not exe:
        return False
    script = DEV_SCRIPTS / "run_vagrant.sh"
    if _is_windows():
        # Vagrant on Windows still needs bash for .sh; require WSL
        if not _wsl_available() or not _exists(script):
            return False
        _spawn([
            "wsl.exe",
            "bash",
            "-lc",
            f"cd '{ROOT.as_posix()}' && ./scripts/dev/run_vagrant.sh",
        ], env=_env_with_port(port, env))
        return True
    if _exists(script):
        _spawn(["bash", str(script)], env=_env_with_port(port, env))
        return True
    return False


def _launch_vm_debug_wrapper(port: int, open_code: bool, env: Optional[Mapping[str, str]] = None) -> bool:
    """
    Use the project’s cross-platform wrapper to start a debug environment.
    On Windows prefer the .ps1; on POSIX use the .py or .sh.
    """
    ps1 = DEV_SCRIPTS / "run_vm_debug.ps1"
    cli_py = PYTHON_SCRIPTS / "run_vm_debug.py"
    sh = DEV_SCRIPTS / "run_vm_debug.sh"

    if _is_windows():
        if _exists(ps1):
            args = [
                _powershell_exe(),
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(ps1),
            ]
            if open_code:
                args += ["--", "--open-code"]
            _spawn(args, env=_env_with_port(port, env))
            return True
        # If no PS1, try WSL bash for .sh
        if _wsl_available() and _exists(sh):
            oc = "--open-code" if open_code else ""
            _spawn([
                "wsl.exe",
                "bash",
                "-lc",
                f"cd '{ROOT.as_posix()}' && ./scripts/dev/run_vm_debug.sh {oc}".strip(),
            ], env=_env_with_port(port, env))
            return True
        # Fallback to Python CLI if present
        if _exists(cli_py):
            cmd = [sys.executable, str(cli_py)]
            if open_code:
                cmd.append("--open-code")
            _spawn(cmd, env=_env_with_port(port, env))
            return True
        return False

    # POSIX
    if _exists(cli_py):
        cmd = [sys.executable, str(cli_py)]
        if open_code:
            cmd.append("--open-code")
        _spawn(cmd, env=_env_with_port(port, env))
        return True
    if _exists(sh):
        oc = ["--open-code"] if open_code else []
        _spawn(["bash", str(sh), *oc], env=_env_with_port(port, env))
        return True
    return False


def _launch_local_debug(port: int, env: Optional[Mapping[str, str]] = None) -> None:
    """Start current app under debugpy, locally."""
    # Use python -m debugpy to avoid relying on a 'debugpy' console script.
    cmd = [
        sys.executable,
        "-Xfrozen_modules=off",
        "-m", "debugpy",
        "--listen", str(port),
        "--wait-for-client",
        str((ROOT / "main.py")),
    ]
    _spawn(cmd, env=_env_with_port(port, env))


# --------------------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------------------
def launch_vm_debug(
    *,
    prefer: str | None = None,
    open_code: bool = False,
    port: int = 5678,
    skip_deps: bool = False,
    preview_plugin: str | None = None,
    preview_manifest: str | None = None,
    preview_profile: str | None = None,
) -> None:
    """
    Start CoolBox in a VM/container or locally under debugpy, waiting for an attach.
    Never executes .sh directly on Windows, thus avoiding WinError 193.

    prefer: 'docker' | 'podman' | 'vagrant' selects first strategy to try.
    open_code: if True, wrappers may open VS Code.
    port: debug server port.
    skip_deps: accepted for API compatibility; ignored here.
    """
    env = _env_with_port(port)
    if preview_plugin:
        env["COOLBOX_PLUGIN_PREVIEW"] = preview_plugin
    if preview_manifest:
        env["COOLBOX_PLUGIN_PREVIEW_MANIFEST"] = preview_manifest
    if preview_profile:
        env["COOLBOX_PLUGIN_PREVIEW_PROFILE"] = preview_profile
    logger.info("Launching debug environment (prefer=%s, port=%s, open_code=%s)", prefer, port, open_code)

    tried: list[str] = []

    def _try(name: str, fn) -> bool:
        tried.append(name)
        try:
            ok = fn(port, env)
            if ok:
                logger.info("Selected backend: %s", name)
                return True
        except Exception as exc:
            logger.warning("Backend %s failed: %s", name, exc)
        return False

    # explicit preference first
    if prefer:
        prefer = prefer.lower()
        if prefer in {"docker", "podman"} and _try("docker/podman", _launch_docker):
            return
        if prefer == "vagrant" and _try("vagrant", _launch_vagrant):
            return
        # If preferred fails, continue to generic order below.

    # generic order
    if _try("vm_debug_wrapper", lambda p, e: _launch_vm_debug_wrapper(p, open_code, e)):
        return
    if _try("docker/podman", _launch_docker):
        return
    if _try("vagrant", _launch_vagrant):
        return

    logger.warning("No VM backend available after trying: %s. Running locally under debugpy.", ", ".join(tried))
    _launch_local_debug(port, env)


__all__ = ["launch_vm_debug", "available_backends"]
