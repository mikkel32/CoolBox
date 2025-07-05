from __future__ import annotations

"""Helpers for loading and applying application icons."""

from pathlib import Path
import os
import sys
import tempfile
import ctypes

from .assets import asset_path, assets_base
from .helpers import log

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

# Default filenames searched when locating logo images if custom paths are not
# provided via environment variables. This allows flexibility in where assets
# are stored while still providing sensible fallbacks.
_PNG_NAMES = [
    "coolbox_logo.png",
    "coolbox.png",
    "logo.png",
]

_ICO_NAMES = [
    "coolbox_logo.ico",
    "coolbox.ico",
    "logo.ico",
]


def _find_logo(names: list[str]) -> Path | None:
    """Search ``assets`` directories for the first existing file in *names*."""

    base = assets_base() / "assets"
    for sub in ("images", "icons", ""):
        folder = base / sub if sub else base
        for name in names:
            path = folder / name
            if path.is_file():
                return path
    return None


def logo_paths() -> tuple[Path, Path]:
    """Return paths to the CoolBox logo image (PNG) and icon (ICO).

    This function first checks the ``COOLBOX_LOGO_PNG`` and
    ``COOLBOX_LOGO_ICO`` environment variables. If those variables are not set
    or the files do not exist, several common filenames are searched for within
    the bundled ``assets`` directories. The search stops at the first existing
    file found for each format, providing flexibility for custom packaging or
    overrides without sacrificing sensible defaults.
    """

    env_png = os.environ.get("COOLBOX_LOGO_PNG")
    env_ico = os.environ.get("COOLBOX_LOGO_ICO")

    png = Path(env_png) if env_png and Path(env_png).is_file() else _find_logo(_PNG_NAMES)
    if png is None:
        png = asset_path("images", "coolbox_logo.png")

    ico = Path(env_ico) if env_ico and Path(env_ico).is_file() else _find_logo(_ICO_NAMES)
    if ico is None:
        ico = asset_path("images", "coolbox_logo.ico")

    return png, ico


def _load_image(path: Path) -> "Image.Image | None":
    if Image is None:
        return None
    try:
        return Image.open(path)
    except Exception:  # pragma: no cover - best effort
        return None


def set_window_icon(
    window,
    callback: "Callable[[str, str], None] | None" = None,
) -> tuple[object | None, object | None, str | None]:
    """Set the application icon on *window* and return icon objects.

    Parameters
    ----------
    window:
        The Tk-compatible window on which to set the icon.
    callback:
        Optional callable ``callback(event, detail)`` invoked for debugging
        during each step of the icon setup process. If omitted, :func:`log`
        is used.

    Returns
    -------
    tuple
        ``(photo, ctk_image, tmp_icon)`` where ``photo`` is the ``tk.PhotoImage``
        used for ``iconphoto``, ``ctk_image`` is a ``CTkImage`` if available, and
        ``tmp_icon`` is the path to any temporary ``.ico`` file created on
        Windows.
    """

    def emit(event: str, detail: str) -> None:
        if callback is not None:
            try:
                callback(event, detail)
            except Exception as exc:  # pragma: no cover - user callback
                log(f"Icon callback error: {exc}")
        else:
            log(f"icon:{event} - {detail}")

    png, ico = logo_paths()
    emit("resolved_png", str(png))
    emit("resolved_ico", str(ico))

    photo = None
    ctk_image = None
    tmp_path: str | None = None

    image = _load_image(png) if png.is_file() else None
    if image is not None:
        emit("load_image", str(png))

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
            emit("iconphoto", str(png))

        if sys.platform.startswith("win"):
            ico_path = ico if ico.is_file() else None
            if ico_path is None and image is not None and Image:
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp:
                        image.save(tmp, format="ICO")
                    ico_path = Path(tmp.name)
                    tmp_path = tmp.name
                    emit("convert_ico", tmp_path)
                except Exception:  # pragma: no cover - optional feature
                    emit("error", "failed_temp_ico")
                    ico_path = None
            if ico_path is not None:
                try:
                    window.iconbitmap(str(ico_path))
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoolBox")
                    emit("iconbitmap", str(ico_path))
                except Exception:  # pragma: no cover - optional feature
                    emit("error", "iconbitmap")

    except Exception as exc:  # pragma: no cover - best effort
        emit("error", str(exc))

    if sys.platform == "darwin":
        try:  # pragma: no cover - optional feature
            from AppKit import NSApplication, NSImage

            path = str(ico if ico.is_file() else png)
            ns_image = NSImage.alloc().initByReferencingFile_(path)
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
            emit("dock_icon", path)
        except Exception:
            emit("error", "dock_icon")

    return photo, ctk_image, tmp_path

