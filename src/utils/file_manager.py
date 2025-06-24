"""File management utilities."""

from pathlib import Path
from typing import Optional
from tkinter import filedialog
import shutil


_DEFAULT_FILETYPES = [
    ("All files", "*.*"),
    ("Text files", "*.txt"),
    ("Python files", "*.py"),
]


def read_text(path: str) -> str:
    return Path(path).read_text()


def write_text(path: str, data: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data)


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


def copy_file(src: str, dest: str, overwrite: bool = False) -> Path:
    """Copy *src* file to *dest* and return the destination path."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists() and not overwrite:
        raise FileExistsError(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy2(src_path, dest_path))


def move_file(src: str, dest: str, overwrite: bool = False) -> Path:
    """Move *src* file to *dest* and return the new path."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists() and not overwrite:
        raise FileExistsError(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    return src_path.rename(dest_path)


def delete_file(path: str) -> None:
    """Delete the file at *path* if it exists."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def list_files(directory: str, pattern: str = "*") -> list[Path]:
    """Return a list of files in *directory* matching *pattern*."""
    return list(Path(directory).glob(pattern))


def copy_dir(src: str, dest: str, overwrite: bool = False) -> Path:
    """Recursively copy directory *src* to *dest*."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists():
        if overwrite:
            shutil.rmtree(dest_path)
        else:
            raise FileExistsError(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_path, dest_path)
    return dest_path


def move_dir(src: str, dest: str, overwrite: bool = False) -> Path:
    """Move directory *src* to *dest*."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists():
        if overwrite:
            shutil.rmtree(dest_path)
        else:
            raise FileExistsError(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    return Path(shutil.move(str(src_path), str(dest_path)))


def delete_dir(path: str) -> None:
    """Recursively delete *path* if it exists."""
    shutil.rmtree(path, ignore_errors=True)
