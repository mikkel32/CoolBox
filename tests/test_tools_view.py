import os
import unittest
from src.app import CoolBoxApp
from src.views.tools_view import ToolsView


class TestToolsView(unittest.TestCase):
    @unittest.skipIf(os.environ.get("DISPLAY") is None, "No display available")
    def test_filter_resets_label_colors(self) -> None:
        app = CoolBoxApp()
        view: ToolsView = app.views["tools"]
        # Grab first tool item
        frame, name, desc, name_lbl, desc_lbl, cmd, default_name, default_desc = view._tool_items[0]

        # Filter by tool name to trigger accent color
        view.search_var.set(name)
        view._filter_tools()
        accent = app.theme.get_theme().get("accent_color", "#1faaff")
        self.assertEqual(name_lbl.cget("text_color"), accent)
        self.assertEqual(desc_lbl.cget("text_color"), accent)

        # Clear filter and ensure colors reset
        view.search_var.set("")
        view._filter_tools()
        self.assertEqual(name_lbl.cget("text_color"), default_name)
        self.assertEqual(desc_lbl.cget("text_color"), default_desc)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
