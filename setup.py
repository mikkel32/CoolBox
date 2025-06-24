"""Development setup script."""
import subprocess
import sys

from src.utils.helpers import log


def install() -> None:
    packages = ["Pillow"]
    for pkg in packages:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    log("Packages installed.")


if __name__ == "__main__":
    install()
