import json
from src.utils.theme import ThemeManager


def test_apply_theme(tmp_path):
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#ff0000"})
    theme_file = tmp_path / "custom_theme.json"
    assert theme_file.exists()
    data = json.loads(theme_file.read_text())
    assert data["CTk"]["color_scale"]["accent_color"] == "#ff0000"
