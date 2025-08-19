"""File management utilities."""

from pathlib import Path
from typing import Optional, Any, Iterable
import tempfile
import os
import json
from tkinter import filedialog
import shutil
import logging


logger = logging.getLogger(__name__)


class FileManagerError(Exception):
    """Custom exception for file management failures."""
    pass


_DEFAULT_FILETYPES = [
    ("All files", "*.*"),
    ("Text files", "*.txt"),
    ("Python files", "*.py"),
]


def read_text(path: str | Path, encoding: str = "utf-8") -> str:
    """Return text from *path* decoded using *encoding*."""
    try:
        return Path(path).read_text(encoding=encoding)
    except OSError as e:
        logger.error("read_text failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to read text from {path}") from e


def write_text(path: str | Path, data: str, encoding: str = "utf-8") -> None:
    """Write *data* to *path* using *encoding*."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding=encoding)
    except OSError as e:
        logger.error("write_text failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to write text to {path}") from e


def read_lines(path: str | Path, encoding: str = "utf-8") -> list[str]:
    """Return list of lines from *path* without trailing newlines."""
    return read_text(path, encoding=encoding).splitlines()


def write_lines(path: str | Path, lines: Iterable[str], encoding: str = "utf-8") -> None:
    """Write each item of *lines* joined by newline to *path*."""
    write_text(path, "\n".join(lines), encoding=encoding)


def read_bytes(path: str | Path) -> bytes:
    """Return binary data from *path*."""
    try:
        return Path(path).read_bytes()
    except OSError as e:
        logger.error("read_bytes failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to read bytes from {path}") from e


def write_bytes(path: str | Path, data: bytes) -> None:
    """Write binary *data* to *path* creating directories if needed."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except OSError as e:
        logger.error("write_bytes failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to write bytes to {path}") from e


def read_json(path: str | Path, encoding: str = "utf-8") -> Any:
    """Return parsed JSON from *path* using *encoding*."""
    return json.loads(read_text(path, encoding=encoding))


def write_json(path: str | Path, obj: Any, encoding: str = "utf-8") -> None:
    """Write *obj* as JSON to *path* atomically using *encoding*."""
    atomic_write(path, json.dumps(obj, indent=2), encoding=encoding)


def atomic_write(path: str | Path, data: str, encoding: str = "utf-8") -> None:
    """Atomically write *data* to *path* using *encoding*."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding=encoding, delete=False, dir=p.parent
        ) as fh:
            fh.write(data)
        os.replace(fh.name, p)
    except OSError as e:
        logger.error("atomic_write failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to atomically write to {path}") from e


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Atomically write binary *data* to *path*."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=p.parent) as fh:
            fh.write(data)
        os.replace(fh.name, p)
    except OSError as e:
        logger.error("atomic_write_bytes failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to atomically write bytes to {path}") from e


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
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy2(src_path, dest_path))
    except OSError as e:
        logger.error("copy_file failed from %s to %s: %s", src, dest, e)
        raise FileManagerError(f"Failed to copy {src} to {dest}") from e


def move_file(src: str, dest: str, overwrite: bool = False) -> Path:
    """Move *src* file to *dest* and return the new path."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists() and not overwrite:
        raise FileExistsError(dest)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        return src_path.rename(dest_path)
    except OSError as e:
        logger.error("move_file failed from %s to %s: %s", src, dest, e)
        raise FileManagerError(f"Failed to move {src} to {dest}") from e


def delete_file(path: str) -> None:
    """Delete the file at *path* if it exists."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.error("delete_file failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to delete file {path}") from e


def list_files(directory: str, pattern: str = "*") -> list[Path]:
    """Return a list of files in *directory* matching *pattern*."""
    try:
        return list(Path(directory).glob(pattern))
    except OSError as e:
        logger.error("list_files failed for %s: %s", directory, e)
        raise FileManagerError(f"Failed to list files in {directory}") from e


def copy_dir(src: str, dest: str, overwrite: bool = False) -> Path:
    """Recursively copy directory *src* to *dest*."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists():
        if overwrite:
            try:
                shutil.rmtree(dest_path)
            except OSError as e:
                logger.error("copy_dir failed removing %s: %s", dest, e)
                raise FileManagerError(f"Failed to remove {dest}") from e
        else:
            raise FileExistsError(dest)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_path, dest_path)
        return dest_path
    except OSError as e:
        logger.error("copy_dir failed from %s to %s: %s", src, dest, e)
        raise FileManagerError(f"Failed to copy directory {src} to {dest}") from e


def move_dir(src: str, dest: str, overwrite: bool = False) -> Path:
    """Move directory *src* to *dest*."""
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists():
        if overwrite:
            try:
                shutil.rmtree(dest_path)
            except OSError as e:
                logger.error("move_dir failed removing %s: %s", dest, e)
                raise FileManagerError(f"Failed to remove {dest}") from e
        else:
            raise FileExistsError(dest)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(src_path), str(dest_path)))
    except OSError as e:
        logger.error("move_dir failed from %s to %s: %s", src, dest, e)
        raise FileManagerError(f"Failed to move directory {src} to {dest}") from e


def delete_dir(path: str) -> None:
    """Recursively delete *path* if it exists."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.error("delete_dir failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to delete directory {path}") from e


def ensure_dir(path: str) -> Path:
    """Create directory *path* if needed and return ``Path`` object."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("ensure_dir failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to ensure directory {path}") from e
    return p


def touch_file(path: str, exist_ok: bool = True) -> Path:
    """Create or update file *path* and return ``Path`` object."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=exist_ok)
    except OSError as e:
        logger.error("touch_file failed for %s: %s", path, e)
        raise FileManagerError(f"Failed to touch file {path}") from e
    return p
