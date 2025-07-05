import re
import tkinter as tk
from tkinter import font as tkfont


# ----------------------------------------------------------------------------
# Basic widget aliases
# ----------------------------------------------------------------------------
CTkBaseClass = tk.Widget


_UNKNOWN_OPT_RE = re.compile(r"unknown option \"-([^\"]+)\"")


def _wrap(base: type[tk.Widget]):
    """Return a wrapper class that ignores unsupported options."""

    class Wrapper(base):
        def __init__(self, master: tk.Misc | None = None, **kwargs):
            while True:
                try:
                    super().__init__(master, **kwargs)
                    break
                except tk.TclError as exc:  # pragma: no cover - depends on options
                    match = _UNKNOWN_OPT_RE.search(str(exc))
                    if not match:
                        raise
                    kwargs.pop(match.group(1), None)

        def configure(self, cnf: dict | None = None, **kwargs):  # type: ignore[override]
            if cnf:
                kwargs.update(cnf)
            while kwargs:
                try:
                    return super().configure(**kwargs)
                except tk.TclError as exc:  # pragma: no cover - depends on options
                    match = _UNKNOWN_OPT_RE.search(str(exc))
                    if not match:
                        raise
                    kwargs.pop(match.group(1), None)
            return super().configure()

        config = configure

        def cget(self, option: str):  # type: ignore[override]
            try:
                return super().cget(option)
            except tk.TclError as exc:  # pragma: no cover - depends on options
                match = _UNKNOWN_OPT_RE.search(str(exc))
                if match:
                    return None
                raise

    Wrapper.__name__ = f"CTk{base.__name__[2:]}" if base.__name__.startswith("Tk") else f"CTk{base.__name__}"
    Wrapper.__qualname__ = Wrapper.__name__
    return Wrapper


CTk = _wrap(tk.Tk)
CTkToplevel = _wrap(tk.Toplevel)
CTkFrame = _wrap(tk.Frame)
CTkButton = _wrap(tk.Button)
CTkLabel = _wrap(tk.Label)
CTkEntry = _wrap(tk.Entry)
CTkSwitch = _wrap(tk.Checkbutton)
CTkProgressBar = _wrap(tk.Frame)
# ``tk.OptionMenu`` requires an initial value argument which our simplified
# wrapper does not handle.  Using ``tk.Frame`` avoids initialization errors
# and provides a container the application can still pack/place.
CTkOptionMenu = _wrap(tk.Frame)
CTkSegmentedButton = _wrap(tk.Frame)
CTkTabview = _wrap(tk.Frame)
CTkScrollableFrame = _wrap(tk.Frame)
CTkRadioButton = _wrap(tk.Radiobutton)
CTkCheckBox = _wrap(tk.Checkbutton)
CTkSlider = _wrap(tk.Scale)
CTkTextbox = _wrap(tk.Text)
CTkFont = _wrap(tkfont.Font)


# ----------------------------------------------------------------------------
# Variable classes
# ----------------------------------------------------------------------------
class StringVar(tk.StringVar):
    pass


class IntVar(tk.IntVar):
    pass


class DoubleVar(tk.DoubleVar):
    pass


class BooleanVar(tk.BooleanVar):
    pass


# ----------------------------------------------------------------------------
# Appearance helpers
# ----------------------------------------------------------------------------
_appearance_mode = "dark"
_color_theme = "blue"


def set_appearance_mode(mode: str) -> None:
    global _appearance_mode
    _appearance_mode = mode


def get_appearance_mode() -> str:
    return _appearance_mode


def set_default_color_theme(theme: str) -> None:
    global _color_theme

    _color_theme = theme


def get_default_color_theme() -> str:
    return _color_theme


__all__ = [
    name
    for name in globals()
    if name.startswith("CTk")
    or name.endswith("Var")
    or name.startswith("set_")
    or name.startswith("get_")
]
