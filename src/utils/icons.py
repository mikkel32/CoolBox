from __future__ import annotations

"""Helpers for loading and applying application icons."""

from pathlib import Path
import os
import sys
import tempfile
import ctypes
import atexit

from .assets import asset_path
from .helpers import log

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - optional runtime dep
    ctk = None  # type: ignore

try:
    from PIL import Image, ImageTk  # type: ignore
    if not hasattr(Image, "open"):
        raise ImportError
except Exception:  # pragma: no cover - pillow optional or stub detected
    try:
        from ..ensure_deps import ensure_pillow

        ensure_pillow()
        import importlib

        for name in list(sys.modules):
            if name.startswith("PIL"):
                sys.modules.pop(name)
        importlib.invalidate_caches()
        Image = importlib.import_module("PIL.Image")  # type: ignore
        ImageTk = importlib.import_module("PIL.ImageTk")  # type: ignore
        if not hasattr(Image, "open"):
            raise ImportError
    except Exception:
        Image = None  # type: ignore
        ImageTk = None  # type: ignore

__all__ = ["logo_paths", "set_window_icon"]


def _notify(callback, message: str) -> None:
    """Dispatch *message* to *callback* and optionally log it."""
    if callback:
        try:
            callback(message)
        except Exception:
            pass
        log(message)


def _search_logo(filename: str, callback=None) -> Path:
    """Attempt to locate *filename* across common directories."""

    xdg_dirs = []
    xdg_env = os.environ.get("XDG_DATA_DIRS")
    if xdg_env:
        xdg_dirs.extend(Path(p) / "icons" for p in xdg_env.split(":"))

    extra_dirs = [
        Path(os.environ.get("COOLBOX_ICON_DIR", "")),
        Path("/usr/local/share/icons"),
        Path("/usr/share/icons"),
        Path("/usr/share/pixmaps"),
        Path("/usr/share/icons/hicolor"),
        Path.home() / ".icons",
    ] + xdg_dirs

    candidates = [
        Path(os.environ.get("COOLBOX_ASSETS", "")) / "assets" / "images",
        Path(__file__).resolve().parents[2] / "assets" / "images",
        Path.cwd(),
        Path(sys.executable).resolve().parent,
        Path.home() / ".local" / "share" / "icons",
    ] + extra_dirs

    for base in candidates:
        p = base / filename
        if p.is_file():
            _notify(callback, f"Found {filename} at {p}")
            return p

    for base in candidates:
        if base.is_dir():
            try:
                p = next(base.rglob(filename))
                _notify(callback, f"Located {filename} via search in {base}")
                return p
            except StopIteration:
                continue

    fallback = asset_path("images", filename)
    _notify(callback, f"Falling back to asset path {fallback}")
    return fallback


def logo_paths(callback=None) -> tuple[Path, Path]:
    """Return paths to the CoolBox logo image and icon.

    The locations can be overridden using the environment variables
    ``COOLBOX_LOGO_PNG`` and ``COOLBOX_LOGO_ICO``. If not set, the files are
    resolved from :func:`asset_path`.
    """

    png_env = os.environ.get("COOLBOX_LOGO_PNG")
    ico_env = os.environ.get("COOLBOX_LOGO_ICO")
    png = Path(png_env) if png_env else _search_logo("coolbox_logo.png", callback)
    ico = Path(ico_env) if ico_env else _search_logo("coolbox_logo.ico", callback)
    return png, ico


def _load_image(path: Path, callback=None) -> "Image.Image | None":
    if Image is None:
        _notify(callback, "Pillow not available, skipping image load")
        return None
    try:
        _notify(callback, f"Loading image from {path}")
        img = Image.open(path)
        if max(img.size) > 256:
            orig = img.size
            img = img.resize((256, 256), Image.LANCZOS)
            _notify(callback, f"Resized icon from {orig} to {img.size}")
        return img
    except Exception as exc:  # pragma: no cover - best effort
        _notify(callback, f"Failed to load image {path}: {exc}")
        return None


def _apply_iconphoto(window, photo, callback=None) -> None:
    """Apply *photo* to *window* and as the default for new windows."""
    try:
        window.tk.call("wm", "iconphoto", window._w, "-default", photo)
    except Exception as exc:
        _notify(callback, f"tk.call iconphoto failed: {exc}")
        try:
            window.iconphoto(True, photo)
        except Exception as exc2:  # pragma: no cover - best effort
            _notify(callback, f"iconphoto failed: {exc2}")


def _apply_iconbitmap(window, ico_path: Path, callback=None) -> None:
    """Apply the bitmap *ico_path* to *window*."""
    try:
        window.iconbitmap(str(ico_path))
        if sys.platform.startswith("win"):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoolBox")
    except Exception as exc:  # pragma: no cover - optional feature
        _notify(callback, f"iconbitmap failed: {exc}")


def set_window_icon(window, *, callback=None) -> tuple[object | None, object | None, str | None]:
    """Set the application icon on *window* and return icon objects.

    Returns a tuple ``(photo, ctk_image, tmp_icon)`` where ``photo`` is the
    ``tk.PhotoImage`` used for ``iconphoto``, ``ctk_image`` is a ``CTkImage``
    if available and ``tmp_icon`` is the path of any temporary ``.ico`` file
    created on Windows.
    """

    png, ico = logo_paths(callback)
    photo = None
    ctk_image = None
    tmp_path: str | None = None

    image = _load_image(png, callback) if png.is_file() else None
    if not png.is_file():
        _notify(callback, f"Icon PNG not found: {png}")

    try:
        if png.is_file():
            _notify(callback, f"Applying icon photo from {png}")
            if ImageTk and image is not None:
                photo = ImageTk.PhotoImage(image)
            else:
                import tkinter as tk

                photo = tk.PhotoImage(file=str(png))  # type: ignore
            if ctk and hasattr(ctk, "CTkImage") and image is not None:
                ctk_image = ctk.CTkImage(
                    light_image=image, dark_image=image, size=image.size
                )
            _apply_iconphoto(window, photo, callback)

        ico_path = ico if ico.is_file() else None
        if ico_path is None and image is not None and Image:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp:
                    image.save(tmp, format="ICO")
                ico_path = Path(tmp.name)
                tmp_path = tmp.name
                atexit.register(lambda p=tmp_path: Path(p).unlink(missing_ok=True))
            except Exception:  # pragma: no cover - optional feature
                ico_path = None
        if ico_path is not None:
            _apply_iconbitmap(window, ico_path, callback)
        
    except Exception:  # pragma: no cover - best effort
        _notify(callback, "Failed to set Windows icon")

    if sys.platform == "darwin":
        try:  # pragma: no cover - optional feature
            from AppKit import NSApplication, NSImage

            path = str(ico if ico.is_file() else png)
            ns_image = NSImage.alloc().initByReferencingFile_(path)
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
        except Exception:
            pass

    return photo, ctk_image, tmp_path
