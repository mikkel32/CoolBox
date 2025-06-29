"""Helper utilities for launching the debug environment in a VM or locally."""

from __future__ import annotations

import os
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Iterable, List

from src.utils.helpers import find_free_port


class VMManager:
    """Manage launching CoolBox inside various VM backends."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2]

    # ------------------------------------------------------------------
    # Backend detection helpers
    # ------------------------------------------------------------------
    def pick_backend(self, prefer: str | None) -> Iterable[str]:
        """Return an ordered list of VM backends to try."""

        prefer = prefer or os.environ.get("PREFER_VM", "auto").lower()
        if prefer == "vagrant":
            return ("vagrant", "docker", "podman")
        if prefer == "docker":
            return ("docker", "podman", "vagrant")
        if prefer == "podman":
            return ("podman", "docker", "vagrant")
        return ("docker", "podman", "vagrant")

    def available_backends(self) -> List[str]:
        """Return a list of installed VM backends."""

        return [b for b in ("docker", "podman", "vagrant") if shutil.which(b)]

    # ------------------------------------------------------------------
    # Launch helpers
    # ------------------------------------------------------------------
    def _run_local_debug(self, port: int) -> None:
        """Launch the application locally under debugpy."""

        env = os.environ.copy()
        env["DEBUG_PORT"] = str(port)
        if os.environ.get("DISPLAY") is None and not shutil.which("xvfb-run"):
            try:
                from pyvirtualdisplay import Display

                display = Display()
                display.start()
                try:
                    subprocess.check_call(
                        [
                            sys.executable,
                            "-Xfrozen_modules=off",
                            "-m",
                            "debugpy",
                            "--listen",
                            str(port),
                            "--wait-for-client",
                            str(self.root / "main.py"),
                        ],
                        env=env,
                    )
                finally:
                    display.stop()
                return
            except Exception:
                print("warning: no display and unable to start virtual display")
        subprocess.check_call([str(self.root / "scripts" / "run_debug.sh")], env=env)

    def launch_debug(self, prefer: str | None = None, *, open_code: bool = False, port: int = 5678) -> None:
        """Launch CoolBox for debugging using available VM backends."""

        if port <= 0:
            port = find_free_port()

        if open_code:
            if shutil.which("code"):
                subprocess.Popen(["code", str(self.root)])
            else:
                print("warning: 'code' command not found; cannot open Visual Studio Code")

        for name in self.pick_backend(prefer):
            if shutil.which(name):
                print(f"Launching CoolBox in {name} for debugging...")
                env = os.environ.copy()
                env["DEBUG_PORT"] = str(port)
                if name in {"docker", "podman"}:
                    script = self.root / "scripts" / "run_devcontainer.sh"
                    subprocess.check_call([str(script), name], env=env)
                else:
                    script = self.root / "scripts" / "run_vagrant.sh"
                    subprocess.check_call([str(script)], env=env)
                return

        print("No VM backend available; launching locally under debugpy...")
        self._run_local_debug(port)


def available_backends() -> List[str]:
    """Return installed VM backends."""

    return VMManager().available_backends()


def launch_vm_debug(
    prefer: str | None = None,
    *,
    open_code: bool = False,
    port: int = 5678,
) -> None:
    """Launch CoolBox inside a VM or fall back to local debugging."""

    VMManager().launch_debug(prefer=prefer, open_code=open_code, port=port)
