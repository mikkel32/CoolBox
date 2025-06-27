import os
import subprocess
import shutil
from pathlib import Path
from typing import Iterable


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


def launch_vm_debug(
    prefer: str | None = None,
    *,
    open_code: bool = False,
    port: int = 5678,
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

    if open_code and shutil.which("code"):
        # Launch VS Code in the background so it's ready when the VM starts
        subprocess.Popen(["code", str(root)])

    backend = prefer or os.environ.get("PREFER_VM", "auto").lower()
    for name in _pick_backend(backend):
        if shutil.which(name):
            if name in {"docker", "podman"}:
                script = root / "scripts" / "run_devcontainer.sh"
                env = os.environ.copy()
                env["DEBUG_PORT"] = str(port)
                subprocess.check_call([str(script), name], env=env)
            else:
                script = root / "scripts" / "run_vagrant.sh"
                env = os.environ.copy()
                env["DEBUG_PORT"] = str(port)
                subprocess.check_call([str(script)], env=env)
            break
    else:
        # Neither docker nor vagrant available; run locally under debugpy
        env = os.environ.copy()
        env["DEBUG_PORT"] = str(port)
        subprocess.check_call([str(root / "scripts" / "run_debug.sh")], env=env)
