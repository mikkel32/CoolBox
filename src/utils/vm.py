import os
import shutil
from pathlib import Path
from typing import Iterable, List

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

    if prefer == "vagrant":
        return ("vagrant", "docker", "podman")
    if prefer == "docker":
        return ("docker", "podman", "vagrant")
    if prefer == "podman":
        return ("podman", "docker", "vagrant")
    # auto / unknown
    return ("docker", "podman", "vagrant")


def available_backends() -> List[str]:
    """Return a list of installed VM backends."""
    backends: List[str] = []
    for name in ("docker", "podman", "vagrant"):
        if shutil.which(name):
            backends.append(name)
    return backends


def launch_vm_debug(
    prefer: str | None = None,
    *,
    open_code: bool = False,
    port: int = 5678,
    skip_deps: bool = False,
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
            if skip_deps:
                env["SKIP_DEPS"] = "1"
            if name in {"docker", "podman"}:
                script = root / "scripts" / "run_devcontainer.sh"
                cmd = [str(script), name]
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
    if skip_deps:
        env["SKIP_DEPS"] = "1"
    run_command([str(root / "scripts" / "run_debug.sh")], timeout=None, env=env)
