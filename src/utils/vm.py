import os
import subprocess
import shutil
from pathlib import Path
from typing import Iterable, List


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
            subprocess.Popen(["code", str(root)])
        else:
            print("warning: 'code' command not found; cannot open Visual Studio Code")

    backend = prefer or os.environ.get("PREFER_VM", "auto").lower()
    for name in _pick_backend(backend):
        if shutil.which(name):
            print(f"Launching CoolBox in {name} for debugging...")
            env = os.environ.copy()
            env["DEBUG_PORT"] = str(port)
            if skip_deps:
                env["SKIP_DEPS"] = "1"
            if name in {"docker", "podman"}:
                script = root / "scripts" / "run_devcontainer.sh"
                subprocess.check_call([str(script), name], env=env)
            else:
                script = root / "scripts" / "run_vagrant.sh"
                subprocess.check_call([str(script)], env=env)
            return
    else:
        print("No VM backend available; launching locally under debugpy...")
        env = os.environ.copy()
        env["DEBUG_PORT"] = str(port)
        if skip_deps:
            env["SKIP_DEPS"] = "1"
        subprocess.check_call([str(root / "scripts" / "run_debug.sh")], env=env)
