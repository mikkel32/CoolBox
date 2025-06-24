import subprocess
import shutil
from pathlib import Path


def launch_vm_debug() -> None:
    """Launch CoolBox in a VM or fall back to local debugging."""

    root = Path(__file__).resolve().parents[2]
    if shutil.which("vagrant"):
        subprocess.check_call([str(root / "scripts" / "run_vagrant.sh")])
    elif shutil.which("docker"):
        subprocess.check_call([str(root / "scripts" / "run_devcontainer.sh")])
    else:
        # Neither docker nor vagrant available; run locally under debugpy
        subprocess.check_call([str(root / "scripts" / "run_debug.sh")])
