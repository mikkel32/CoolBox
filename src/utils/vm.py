import os
import shutil
import platform
import subprocess
from pathlib import Path
from typing import Iterable, List
import asyncio

try:
    from .process_utils import (
        run_command,
        run_command_ex,
        run_command_background,
    )
except ImportError:  # pragma: no cover - fallback when run as a script
    from src.utils.process_utils import (
        run_command,
        run_command_ex,
        run_command_background,
    )


def _pick_backend(prefer: str) -> Iterable[str]:
    """Return an ordered list of VM backends to try."""

    if prefer == "wsl":
        return ("wsl", "docker", "podman", "vagrant")
    if prefer == "vagrant":
        return ("vagrant", "docker", "podman", "wsl")
    if prefer == "docker":
        return ("docker", "podman", "vagrant", "wsl")
    if prefer == "podman":
        return ("podman", "docker", "vagrant", "wsl")
    # auto / unknown
    return ("docker", "podman", "vagrant", "wsl")


def available_backends() -> List[str]:
    """Return a list of installed VM backends."""
    backends: List[str] = []
    for name in ("docker", "podman", "vagrant"):
        if shutil.which(name):
            backends.append(name)
    if platform.system() == "Windows" and shutil.which("wsl"):
        backends.append("wsl")
    return backends


def launch_vm_debug(
    prefer: str | None = None,
    *,
    open_code: bool = False,
    port: int = 5678,
    skip_deps: bool = False,
    target: str | None = None,
) -> None:
    """Launch CoolBox inside a VM or fall back to local debugging.

    Parameters
    ----------
    prefer:
        Optional backend to prefer ("docker", "podman" or "vagrant"). If ``None`` the
        environment variable ``PREFER_VM`` is consulted and finally defaults to
        automatic detection.
    open_code:
        If true and the ``code`` command is available, Visual Studio Code will
        be opened with the project folder once the VM starts. This makes it easy
        to attach the debugger using the ``Python: Attach`` configuration.
    target:
        Optional Python script path and arguments to launch instead of
        ``main.py`` inside the VM.
    """

    root = Path(__file__).resolve().parents[2]

    if open_code:
        if shutil.which("code"):
            # Launch VS Code in the background so it's ready when the VM starts
            run_command_background(["code", str(root)], env=os.environ.copy())
        else:
            print("warning: 'code' command not found; cannot open Visual Studio Code")

    backend = prefer or os.environ.get("PREFER_VM", "auto").lower()
    detected = available_backends()
    for name in _pick_backend(backend):
        if name in detected:
            print(f"Launching CoolBox in {name} for debugging...")
            env = os.environ.copy()
            env["DEBUG_PORT"] = str(port)
            if target:
                env["DEBUG_TARGET"] = target
            if skip_deps:
                env["SKIP_DEPS"] = "1"
            if name in {"docker", "podman"}:
                script = root / "scripts" / "run_devcontainer.sh"
                cmd = [str(script), name]
            elif name == "wsl":
                script = root / "scripts" / "run_debug.sh"
                try:
                    wsl_script = subprocess.check_output(
                        ["wsl", "wslpath", "-a", str(script)], text=True
                    ).strip()
                except Exception:
                    wsl_script = str(script).replace("\\", "/")
                    if ":" in wsl_script:
                        drive, rest = wsl_script.split(":", 1)
                        wsl_script = f"/mnt/{drive.lower()}{rest}"
                cmd = ["wsl", "bash", wsl_script]
            else:
                script = root / "scripts" / "run_vagrant.sh"
                cmd = [str(script)]
            _out, code = run_command_ex(cmd, timeout=None, check=False, env=env)
            if code == 0:
                return
            print(f"{name} failed with code {code}; trying next backend")
            continue

    print("No VM backend available; detected none. Launching locally under debugpy.")
    env = os.environ.copy()
    env["DEBUG_PORT"] = str(port)
    if target:
        env["DEBUG_TARGET"] = target
    if skip_deps:
        env["SKIP_DEPS"] = "1"
    run_command([str(root / "scripts" / "run_debug.sh")], timeout=None, env=env)


async def async_launch_vm_debug(
    prefer: str | None = None,
    *,
    open_code: bool = False,
    port: int = 5678,
    skip_deps: bool = False,
    target: str | None = None,
) -> None:
    """Asynchronous wrapper for :func:`launch_vm_debug`."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        launch_vm_debug,
        prefer,
        open_code,
        port,
        skip_deps,
        target,
    )
