"""File management utilities."""

from pathlib import Path
from typing import Optional
from tkinter import filedialog


_DEFAULT_FILETYPES = [
    ("All files", "*.*"),
    ("Text files", "*.txt"),
    ("Python files", "*.py"),
]


def read_text(path: str) -> str:
    return Path(path).read_text()


def write_text(path: str, data: str) -> None:
    Path(path).write_text(data)


def pick_file() -> Optional[str]:
    """Return the path to a file chosen by the user.

    If the user cancels the dialog ``None`` will be returned.
    """

    try:
        filename = filedialog.askopenfilename(title="Select a file", filetypes=_DEFAULT_FILETYPES)
    except Exception:
        # ``filedialog`` requires an active Tk instance.  If it cannot be
        # created or fails for some reason, fall back to ``None`` so the
        # calling code can handle the situation gracefully.
        return None
    return filename or None
