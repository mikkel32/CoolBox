import json
from src.utils.theme import ThemeManager


def test_apply_theme(tmp_path):
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#ff0000"})
    theme_file = tmp_path / "custom_theme.json"
    assert theme_file.exists()
    data = json.loads(theme_file.read_text())
    assert data["CTk"]["color_scale"]["accent_color"] == "#ff0000"


def test_load_theme_missing_file(tmp_path):
    manager = ThemeManager(config_dir=tmp_path)
    # No theme file exists yet; loading should return an empty dict
    assert manager.load_theme() == {}

    # After applying a theme, loading should return the same values
    theme = {"primary_color": "#123456"}
    manager.apply_theme(theme)
    assert manager.load_theme()["primary_color"] == "#123456"
