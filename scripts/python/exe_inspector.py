#!/usr/bin/env python3
"""Compatibility wrapper for ``coolbox.cli.commands.exe_inspector``."""
from __future__ import annotations

from coolbox.cli.commands import exe_inspector as _impl

try:  # pragma: no cover - fallback when executed as a file
    from . import _wrappers
except ImportError:  # pragma: no cover - legacy invocation path
    import importlib.util
    import sys
    from pathlib import Path

    module_name = "scripts.python._wrappers"
    wrappers = sys.modules.get(module_name)
    if wrappers is None:
        spec = importlib.util.spec_from_file_location(
            module_name, Path(__file__).with_name("_wrappers.py")
        )
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise ImportError("Unable to load CLI wrappers helper")
        wrappers = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = wrappers
        spec.loader.exec_module(wrappers)
    _wrappers = wrappers  # type: ignore[assignment]

main = _wrappers.sync_command(globals(), "exe_inspector")

gather_info = _impl.gather_info
_processes_for = _impl._processes_for
_ports_for = _impl._ports_for
_extract_strings = _impl._extract_strings

__all__ = [
    "_extract_strings",
    "_ports_for",
    "_processes_for",
    "gather_info",
    "main",
]


if __name__ == "__main__":
    main()
