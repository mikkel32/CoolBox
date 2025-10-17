"""Rich integration with permissive fallbacks for headless environments."""
from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, TypeAlias

__all__ = [
    "BarColumn",
    "Column",
    "Console",
    "ConsoleType",
    "MofNCompleteColumn",
    "Panel",
    "Progress",
    "ProgressColumn",
    "RICH_AVAILABLE",
    "Table",
    "TaskProgressColumn",
    "Text",
    "TextType",
    "TimeElapsedColumn",
    "box",
]

if TYPE_CHECKING:  # pragma: no cover - typing only imports
    from rich.console import Console
    from rich.table import Table, Column
    from rich.panel import Panel
    from rich.progress import (
        Progress,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        ProgressColumn,
    )
    from rich.text import Text
    from rich import box

    ConsoleType = Console
    TextType = Text
    RICH_AVAILABLE = True
else:
    ConsoleType: TypeAlias = object
    TextType: TypeAlias = str

    _RichConsole = _RichTable = _RichPanel = None
    _RichProgress = _RichBarColumn = _RichTimeElapsedColumn = None
    _RichTaskProgressColumn = _RichMofNCompleteColumn = _RichProgressColumn = None
    _RichColumn = _RichText = None
    _rich_box = None
    RICH_AVAILABLE = False
    try:  # pragma: no cover - runtime import guarded for environments without rich
        from rich.console import Console as _RichConsole
        from rich.table import Table as _RichTable, Column as _RichColumn
        from rich.panel import Panel as _RichPanel
        from rich.progress import (
            Progress as _RichProgress,
            BarColumn as _RichBarColumn,
            TimeElapsedColumn as _RichTimeElapsedColumn,
            TaskProgressColumn as _RichTaskProgressColumn,
            MofNCompleteColumn as _RichMofNCompleteColumn,
            ProgressColumn as _RichProgressColumn,
        )
        from rich.text import Text as _RichText
        from rich import box as _rich_box
        from rich.traceback import install as _rich_tb_install

        _rich_tb_install(show_locals=False)
        RICH_AVAILABLE = True
    except ImportError:
        try:  # pragma: no cover - final attempt to bootstrap rich automatically
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "rich>=13"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            from rich.console import Console as _RichConsole
            from rich.table import Table as _RichTable, Column as _RichColumn
            from rich.panel import Panel as _RichPanel
            from rich.progress import (
                Progress as _RichProgress,
                BarColumn as _RichBarColumn,
                TimeElapsedColumn as _RichTimeElapsedColumn,
                TaskProgressColumn as _RichTaskProgressColumn,
                MofNCompleteColumn as _RichMofNCompleteColumn,
                ProgressColumn as _RichProgressColumn,
            )
            from rich.text import Text as _RichText
            from rich import box as _rich_box

            RICH_AVAILABLE = True
        except Exception:  # pragma: no cover - keep permissive
            RICH_AVAILABLE = False

    if RICH_AVAILABLE:
        Console = _RichConsole  # type: ignore[assignment]
        Table = _RichTable  # type: ignore[assignment]
        Panel = _RichPanel  # type: ignore[assignment]
        Progress = _RichProgress  # type: ignore[assignment]
        BarColumn = _RichBarColumn  # type: ignore[assignment]
        TimeElapsedColumn = _RichTimeElapsedColumn  # type: ignore[assignment]
        TaskProgressColumn = _RichTaskProgressColumn  # type: ignore[assignment]
        MofNCompleteColumn = _RichMofNCompleteColumn  # type: ignore[assignment]
        ProgressColumn = _RichProgressColumn  # type: ignore[assignment]
        Column = _RichColumn  # type: ignore[assignment]
        Text = _RichText  # type: ignore[assignment]
        box = _rich_box  # type: ignore[assignment]
    else:

        class _PlainConsole:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def print(self, *args, **kwargs) -> None:  # pragma: no cover - passthrough
                print(*args, **kwargs)

            def log(self, *args, **kwargs) -> None:  # pragma: no cover - passthrough
                print(*args, **kwargs)

            @property
            def file(self):  # pragma: no cover - compatibility shim
                return sys.stdout

        class _PlainTable:
            def __init__(self, *_, **__):
                self._rows: list[str] = []

            def add_column(self, *_, **__) -> None:
                pass

            def add_row(self, *args, **__) -> None:
                self._rows.append(" ".join(str(arg) for arg in args))

            def __str__(self) -> str:
                return "\n".join(self._rows)

        class _PlainPanel:
            def __init__(self, content, **__):
                self.content = content

            def __str__(self) -> str:
                return str(self.content)

        class _PlainProgress:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def add_task(self, *_, **__):  # pragma: no cover - minimal shim
                return 0

            def advance(self, *_, **__):  # pragma: no cover - minimal shim
                pass

        class _PlainText(str):
            def append(self, ch: str, style: str | None = None) -> None:
                pass

        class _PlainColumn:  # pragma: no cover - shim for API parity
            def __init__(self, *_, **__):
                pass

        class _Box:  # pragma: no cover - placeholder for rich.box
            SIMPLE_HEAVY = None
            ROUNDED = None
            MINIMAL_DOUBLE_HEAD = None

        Console = _PlainConsole  # type: ignore[assignment]
        Table = _PlainTable  # type: ignore[assignment]
        Panel = _PlainPanel  # type: ignore[assignment]
        Progress = _PlainProgress  # type: ignore[assignment]
        BarColumn = TimeElapsedColumn = TaskProgressColumn = MofNCompleteColumn = ProgressColumn = object
        Column = _PlainColumn  # type: ignore[assignment]
        Text = _PlainText  # type: ignore[assignment]
        box = _Box()  # type: ignore[assignment]
