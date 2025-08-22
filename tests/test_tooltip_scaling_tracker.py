import os
import pytest
import customtkinter as ctk
from customtkinter.windows.widgets.scaling import scaling_tracker

from src.components.tooltip import Tooltip


@pytest.mark.skipif(os.environ.get("DISPLAY") is None, reason="No display available")
def test_tooltip_registers_with_scaling_tracker() -> None:
    root = ctk.CTk()
    tip = Tooltip(root, "hello")
    root.update_idletasks()
    assert tip in scaling_tracker.ScalingTracker.window_dpi_scaling_dict
    tip.destroy()
    root.update_idletasks()
    assert tip not in scaling_tracker.ScalingTracker.window_dpi_scaling_dict
    root.destroy()


@pytest.mark.skipif(os.environ.get("DISPLAY") is None, reason="No display available")
def test_tooltip_cleans_up_when_parent_destroyed() -> None:
    root = ctk.CTk()
    tip = Tooltip(root, "bye")
    root.update_idletasks()
    assert tip in scaling_tracker.ScalingTracker.window_dpi_scaling_dict
    root.destroy()
    # process pending events, ignoring errors if the root is already gone
    try:
        root.update()
    except Exception:
        pass
    assert tip not in scaling_tracker.ScalingTracker.window_dpi_scaling_dict
