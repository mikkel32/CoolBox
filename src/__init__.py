"""Public package interface for CoolBox.

This module lazily exposes :class:`CoolBoxApp` and the dependency helper
``ensure_customtkinter`` so importing ``src`` does not immediately pull in heavy
optional dependencies. The actual imports are deferred until the attributes are
accessed via :func:`__getattr__`.
"""

from __future__ import annotations

__all__ = ["CoolBoxApp", "ensure_customtkinter"]


def __getattr__(name: str) -> object:
    if name == "CoolBoxApp":
        from .app import CoolBoxApp as app
        return app
    if name == "ensure_customtkinter":
        from .ensure_deps import ensure_customtkinter as ectk
        return ectk
    raise AttributeError(name)
