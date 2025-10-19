"""SQLite-backed catalog for persisted CoolBox runtime metadata."""

from __future__ import annotations

from .sqlite import Catalog, get_catalog, reset_catalog

__all__ = [
    "Catalog",
    "get_catalog",
    "reset_catalog",
]

