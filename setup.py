"""Install project dependencies with optional dev extras."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from src.utils.helpers import log


REQUIREMENTS_FILE = Path("requirements.txt")
DEV_PACKAGES = ["debugpy", "flake8"]


def install(requirements: Path = REQUIREMENTS_FILE, dev: bool = False) -> None:
    """Install dependencies using pip.

    Parameters
    ----------
    requirements: Path
        Path to the requirements file containing runtime dependencies.
    dev: bool, default False
        If ``True``, install additional development packages.
    """
    if requirements.is_file():
        log(f"Installing requirements from {requirements}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
    else:
        log(f"Requirements file {requirements} not found")

    if dev:
        log("Installing development packages")
        for pkg in DEV_PACKAGES:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    log("Dependencies installed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install CoolBox dependencies")
    parser.add_argument("--dev", action="store_true", help="Install development packages")
    args = parser.parse_args()
    install(dev=args.dev)
