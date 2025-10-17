"""Module executed when running ``python -m coolbox``."""
from __future__ import annotations

from .cli import main


def run() -> None:
    """Entrypoint wrapper to make ``python -m coolbox`` explicit."""

    main()


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    run()
