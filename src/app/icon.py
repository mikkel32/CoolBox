from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import ctypes

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_pillow

    pil = ensure_pillow()
    Image = pil.Image  # type: ignore[attr-defined]
    ImageTk = pil.ImageTk  # type: ignore[attr-defined]

from ..utils.helpers import log


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
        log(msg)
        raise RuntimeError(msg)

    temp_icon: str | None = None
    try:
        image = Image.open(icon_path)
        photo = ImageTk.PhotoImage(image)
        window.iconphoto(True, photo)

        if sys.platform.startswith("win"):
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ico")
                image.save(tmp, format="ICO")
                tmp.close()
                window.iconbitmap(tmp.name)
                try:  # pragma: no cover - best effort
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoolBox")
                except Exception:
                    pass
                temp_icon = tmp.name
            except Exception as exc:
                log(f"Failed to set taskbar icon: {exc}")
                raise RuntimeError(f"Failed to set taskbar icon: {exc}") from exc
    except Exception as exc:
        log(f"Failed to set window icon: {exc}")
        raise RuntimeError(f"Failed to set window icon: {exc}") from exc

    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSImage  # type: ignore

            ns_image = NSImage.alloc().initByReferencingFile_(str(icon_path))
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
        except Exception as exc:
            log(f"Failed to set dock icon: {exc}")
            raise RuntimeError(f"Failed to set dock icon: {exc}") from exc

    return photo, temp_icon
