"""Simple tooltip implementation for CTk widgets."""
from __future__ import annotations

import customtkinter as ctk
from customtkinter.windows.widgets.scaling import scaling_tracker


class Tooltip(ctk.CTkToplevel):
    """Popup tooltip window bound to a widget."""

    def __init__(self, parent: ctk.CTkBaseClass, text: str) -> None:
        super().__init__(parent)
        # Always register the tooltip for DPI scaling. CustomTkinter can lose
        # track of transient windows, which then triggers a ``KeyError`` inside
        # its scaling tracker when DPI changes are checked. Adding the window
        # here keeps the internal dictionaries in sync and calling
        # ``add_window`` repeatedly is safe because the method de-duplicates
        # registrations.
        scaling_tracker.ScalingTracker.add_window(self._set_scaling, self)

        # Ensure tooltip is deregistered even if the parent window destroys it
        # directly. Tkinter does not call our ``destroy`` override when a
        # toplevel is destroyed as part of its parent, so we bind to the
        # ``<Destroy>`` event to perform cleanup in all cases.
        self.bind("<Destroy>", self._on_destroy, add="+")

        self.overrideredirect(True)
        self.withdraw()
        self.label = ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=12))
        self.label.pack(padx=6, pady=3)

    def show(self, x: int, y: int) -> None:
        """Display the tooltip at screen coordinates (x, y)."""
        self.geometry(f"+{x}+{y}")
        self.deiconify()

    def hide(self) -> None:
        """Hide the tooltip."""
        self.withdraw()

    def _on_destroy(self, _event=None) -> None:
        """Remove tooltip from CustomTkinter's scaling tracker."""
        scaling_tracker.ScalingTracker.remove_window(self._set_scaling, self)
        scaling_tracker.ScalingTracker.window_widgets_dict.pop(self, None)
        scaling_tracker.ScalingTracker.window_dpi_scaling_dict.pop(self, None)

    def destroy(self) -> None:  # type: ignore[override]
        """Destroy tooltip and deregister from scaling tracker."""
        self._on_destroy()
        super().destroy()
