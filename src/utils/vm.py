import subprocess
import shutil
from pathlib import Path


def launch_vm_debug() -> None:
    """Launch CoolBox inside Docker or Vagrant for debugging."""
    root = Path(__file__).resolve().parents[1]
    if shutil.which("vagrant"):
        subprocess.check_call([str(root / "scripts" / "run_vagrant.sh")])
    elif shutil.which("docker"):
        subprocess.check_call([str(root / "scripts" / "run_devcontainer.sh")])
    else:
        raise RuntimeError("Neither vagrant nor docker is available")
