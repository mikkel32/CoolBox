from __future__ import annotations

"""Helpers for loading and applying application icons.

The previous implementation attempted to locate logo files across many
system directories and contained a fair bit of platform specific logic.
While flexible, the behaviour was difficult to reason about and resulted in
confusing logs such as repeated "Found" messages.  The helpers below take a
much simpler approach – the logo paths either come from environment
variables or from the bundled ``assets`` directory.  This keeps things
predictable and ensures the same paths are used everywhere.
"""

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




def logo_paths(callback=None) -> tuple[Path, Path]:
    """Return paths to the CoolBox logo image (PNG) and icon (ICO)."""

    png_env = os.environ.get("COOLBOX_LOGO_PNG")
    ico_env = os.environ.get("COOLBOX_LOGO_ICO")

    png = Path(png_env) if png_env else asset_path("images", "coolbox_logo.png")
    ico = Path(ico_env) if ico_env else asset_path("images", "coolbox_logo.ico")

    if callback:
        _notify(callback, f"Using PNG icon at {png}")
        _notify(callback, f"Using ICO icon at {ico}")

    return png, ico


def _load_image(path: Path, callback=None) -> "Image.Image | None":
    """Load ``path`` with Pillow if available and resize large images."""

    if Image is None:
        _notify(callback, "Pillow not available, skipping image load")
        return None

    try:
        img = Image.open(path)
        if max(img.size) > 256:
            img = img.resize((256, 256), Image.LANCZOS)
        _notify(callback, f"Loaded image {path} at size {img.size}")
        return img
    except Exception as exc:  # pragma: no cover - best effort
        _notify(callback, f"Failed to load image {path}: {exc}")
        return None


def _apply_iconphoto(window, photo, callback=None) -> None:
    """Apply *photo* to *window* and make it default for new windows."""
    try:
        window.iconphoto(True, photo)
    except Exception as exc:  # pragma: no cover - best effort
        _notify(callback, f"iconphoto failed: {exc}")


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

    if png.is_file():
        image = _load_image(png, callback)
        _notify(callback, f"Applying icon photo from {png}")
        if ImageTk and image is not None:
            photo = ImageTk.PhotoImage(image)
        else:
            import tkinter as tk

            photo = tk.PhotoImage(file=str(png))  # type: ignore
        if ctk and hasattr(ctk, "CTkImage") and image is not None:
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        _apply_iconphoto(window, photo, callback)
    else:
        _notify(callback, f"Icon PNG not found: {png}")

    ico_path = ico if ico.is_file() else None
    if ico_path is None and photo is not None and Image:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp:
                img = _load_image(png, callback)
                if img:
                    img.save(tmp, format="ICO")
            ico_path = Path(tmp.name)
            tmp_path = tmp.name
            atexit.register(lambda p=tmp_path: Path(p).unlink(missing_ok=True))
        except Exception:  # pragma: no cover - optional feature
            ico_path = None
    if ico_path is not None:
        _apply_iconbitmap(window, ico_path, callback)

    if sys.platform == "darwin":
        try:  # pragma: no cover - optional feature
            from AppKit import NSApplication, NSImage

            path = str(ico if ico.is_file() else png)
            ns_image = NSImage.alloc().initByReferencingFile_(path)
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
        except Exception:
            pass

    return photo, ctk_image, tmp_path
