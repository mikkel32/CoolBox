import os
import customtkinter as ctk
import pytest

from src.components import LineChart, BarChart


@pytest.mark.skipif(os.environ.get("DISPLAY") is None, reason="No display available")
def test_line_chart_separate_canvas():
    root = ctk.CTk()
    chart = LineChart(root, "CPU")
    chart.pack()
    root.update_idletasks()
    # CTkFrame retains its internal canvas
    assert hasattr(chart, "_canvas")
    assert chart._canvas.winfo_exists()
    # Matplotlib canvas stored separately
    assert hasattr(chart, "_mpl_canvas")
    assert chart._mpl_canvas.get_tk_widget().winfo_exists() == 1
    chart.destroy()
    root.destroy()


@pytest.mark.skipif(os.environ.get("DISPLAY") is None, reason="No display available")
def test_bar_chart_separate_canvas():
    root = ctk.CTk()
    chart = BarChart(root, "Per Core")
    chart.pack()
    root.update_idletasks()
    assert hasattr(chart, "_canvas")
    assert chart._canvas.winfo_exists()
    assert hasattr(chart, "_mpl_canvas")
    assert chart._mpl_canvas.get_tk_widget().winfo_exists() == 1
    chart.destroy()
    root.destroy()
