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


def test_get_theme(tmp_path):
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#00ff00"})
    assert manager.get_theme()["accent_color"] == "#00ff00"


def test_export_import_theme(tmp_path):
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#abc123"})
    export_path = tmp_path / "export.json"
    manager.export_theme(export_path)

    new_manager = ThemeManager(config_dir=tmp_path)
    new_manager.import_theme(export_path)
    assert new_manager.get_theme()["accent_color"] == "#abc123"


def test_apply_theme_updates_config(tmp_path):
    class DummyConfig:
        def __init__(self) -> None:
            self.values: dict = {}

        def set(self, key: str, value) -> None:
            self.values[key] = value

    cfg = DummyConfig()
    manager = ThemeManager(config_dir=tmp_path, config=cfg)
    manager.apply_theme({"accent_color": "#ff00ff"})
    assert cfg.values["theme"]["accent_color"] == "#ff00ff"
