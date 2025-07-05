from __future__ import annotations

"""Helpers for loading and applying application icons."""

from pathlib import Path
import os
import sys
import tempfile
import ctypes

from .assets import asset_path

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - optional runtime dep
    ctk = None  # type: ignore

try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover - pillow optional
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

__all__ = ["logo_paths", "set_window_icon"]


def logo_paths() -> tuple[Path, Path]:
    """Return paths to the CoolBox logo image and icon.

    The locations can be overridden using the environment variables
    ``COOLBOX_LOGO_PNG`` and ``COOLBOX_LOGO_ICO``. If not set, the files are
    resolved from :func:`asset_path`.
    """

    png = os.environ.get("COOLBOX_LOGO_PNG")
    ico = os.environ.get("COOLBOX_LOGO_ICO")
    return (
        Path(png) if png else asset_path("images", "coolbox_logo.png"),
        Path(ico) if ico else asset_path("images", "coolbox_logo.ico"),
    )


def _load_image(path: Path) -> "Image.Image | None":
    if Image is None:
        return None
    try:
        return Image.open(path)
    except Exception:  # pragma: no cover - best effort
        return None


def set_window_icon(window) -> tuple[object | None, object | None, str | None]:
    """Set the application icon on *window* and return icon objects.

    Returns a tuple ``(photo, ctk_image, tmp_icon)`` where ``photo`` is the
    ``tk.PhotoImage`` used for ``iconphoto``, ``ctk_image`` is a ``CTkImage``
    if available and ``tmp_icon`` is the path of any temporary ``.ico`` file
    created on Windows.
    """

    png, ico = logo_paths()
    photo = None
    ctk_image = None
    tmp_path: str | None = None

    image = _load_image(png) if png.is_file() else None

    try:
        if png.is_file():
            if ImageTk and image is not None:
                photo = ImageTk.PhotoImage(image)
            else:
                import tkinter as tk

                photo = tk.PhotoImage(file=str(png))  # type: ignore
            if ctk and hasattr(ctk, "CTkImage") and image is not None:
                ctk_image = ctk.CTkImage(light_image=image, size=image.size)
            window.iconphoto(True, photo)

        if sys.platform.startswith("win"):
            ico_path = ico if ico.is_file() else None
            if ico_path is None and image is not None and Image:
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp:
                        image.save(tmp, format="ICO")
                    ico_path = Path(tmp.name)
                    tmp_path = tmp.name
                except Exception:  # pragma: no cover - optional feature
                    ico_path = None
            if ico_path is not None:
                try:
                    window.iconbitmap(str(ico_path))
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoolBox")
                except Exception:  # pragma: no cover - optional feature
                    pass

    except Exception:  # pragma: no cover - best effort
        pass

    if sys.platform == "darwin":
        try:  # pragma: no cover - optional feature
            from AppKit import NSApplication, NSImage

            path = str(ico if ico.is_file() else png)
            ns_image = NSImage.alloc().initByReferencingFile_(path)
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
        except Exception:
            pass

    return photo, ctk_image, tmp_path
