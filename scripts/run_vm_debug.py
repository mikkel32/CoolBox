#!/usr/bin/env python3
"""Launch CoolBox in a VM or container for debugging."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import launch_vm_debug  # noqa: E402

if __name__ == "__main__":
    launch_vm_debug()
