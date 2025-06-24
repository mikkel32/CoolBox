#!/usr/bin/env python3
"""
CoolBox - A Modern Desktop Application
Main entry point for the application
"""
import sys
from pathlib import Path

# Ensure package imports work when running as a script
sys.path.insert(0, str(Path(__file__).parent))

from src import CoolBoxApp


def main():
    """Initialize and run the application"""
    app = CoolBoxApp()
    app.run()


if __name__ == "__main__":
    main()
