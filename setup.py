"""Development setup script."""
import subprocess
import sys
from pathlib import Path


def install() -> None:
    packages = ["Pillow"]
    for pkg in packages:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    print("Packages installed.")


if __name__ == "__main__":
    install()
