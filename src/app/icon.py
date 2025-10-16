from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import ctypes
import logging
from typing import TYPE_CHECKING, Any

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_pillow

    pil = ensure_pillow()
    Image = pil.Image  # type: ignore[attr-defined]
    ImageTk = pil.ImageTk  # type: ignore[attr-defined]

if TYPE_CHECKING:
    from ctypes import LibraryLoader

    _WindllType = LibraryLoader[Any]
else:
    _WindllType = ctypes.LibraryLoader[Any]  # type: ignore[misc]

_windll: _WindllType | None
try:  # pragma: no cover - attribute missing on non-Windows
    _windll = getattr(ctypes, "windll")
except AttributeError:  # pragma: no cover - non-Windows Python build
    _windll = None


logger = logging.getLogger(__name__)


def set_app_icon(window):
    """Set the application icon for *window* and return icon data.

    Returns a tuple ``(photo_image, temp_icon_path)`` where ``photo_image`` is
    the Tk photo image used for the window icon and ``temp_icon_path`` is the
    path to a temporary ``.ico`` file on Windows (``None`` otherwise).
    """
    icon_path = (
        Path(__file__).resolve().parents[2] / "assets" / "images" / "Coolbox_logo.png"
    )
    if not icon_path.is_file():
        msg = f"Icon file not found: {icon_path}"
        logger.error(msg)
        raise RuntimeError(msg)

    temp_icon: str | None = None
    try:
        image = Image.open(icon_path)
        photo = ImageTk.PhotoImage(image, master=window)
        window.iconphoto(True, photo)

        if sys.platform.startswith("win"):
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ico")
                image.save(tmp, format="ICO")
                tmp.close()
                window.iconbitmap(tmp.name)
                try:  # pragma: no cover - best effort
                    if _windll is not None:
                        _windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoolBox")
                except Exception:
                    pass
                temp_icon = tmp.name
            except Exception as exc:
                logger.warning("Failed to set taskbar icon: %s", exc)
                raise RuntimeError(f"Failed to set taskbar icon: {exc}") from exc
    except Exception as exc:
        logger.error("Failed to set window icon: %s", exc)
        raise RuntimeError(f"Failed to set window icon: {exc}") from exc

    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSImage  # type: ignore

            ns_image = NSImage.alloc().initByReferencingFile_(str(icon_path))
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
        except Exception as exc:
            logger.warning("Failed to set dock icon: %s", exc)
            raise RuntimeError(f"Failed to set dock icon: {exc}") from exc

    return photo, temp_icon
