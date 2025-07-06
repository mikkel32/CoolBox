"""Thin shim for the bundled ``customtkinter`` stub.

The real ``customtkinter`` package causes issues when running the project in
headless test environments.  The repository therefore ships a lightweight
replacement under ``src.customtkinter``.  This shim simply exposes the stub
module under the top-level ``customtkinter`` name so imports work the same on
all systems.
"""

from __future__ import annotations

import importlib
module = importlib.import_module("src.customtkinter")

for name in getattr(module, "__all__", dir(module)):
    globals()[name] = getattr(module, name)

__all__ = getattr(
    module, "__all__", [n for n in globals() if not n.startswith("_")]
)
