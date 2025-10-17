from __future__ import annotations

import json
from coolbox.utils.theme import ThemeManager, _ConfigLike


def test_apply_theme(tmp_path) -> None:
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#ff0000"})
    theme_file = tmp_path / "custom_theme.json"
    assert theme_file.exists()
    data = json.loads(theme_file.read_text())
    assert data["CTk"]["color_scale"]["accent_color"] == "#ff0000"


def test_load_theme_missing_file(tmp_path) -> None:
    manager = ThemeManager(config_dir=tmp_path)
    assert manager.load_theme() == {}

    theme = {"primary_color": "#123456"}
    manager.apply_theme(theme)
    loaded = manager.load_theme()
    assert loaded["primary_color"] == "#123456"


def test_get_theme(tmp_path) -> None:
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#00ff00"})
    theme = manager.get_theme()
    assert theme["accent_color"] == "#00ff00"


def test_export_import_theme(tmp_path) -> None:
    manager = ThemeManager(config_dir=tmp_path)
    manager.apply_theme({"accent_color": "#abc123"})
    export_path = tmp_path / "export.json"
    manager.export_theme(str(export_path))

    new_manager = ThemeManager(config_dir=tmp_path)
    new_manager.import_theme(str(export_path))
    assert new_manager.get_theme()["accent_color"] == "#abc123"


def test_apply_theme_updates_config(tmp_path) -> None:
    class DummyConfig(_ConfigLike):
        def __init__(self) -> None:
            self.values: dict[str, dict[str, str]] = {}

        def set(self, key: str, value: dict[str, str]) -> None:
            self.values[key] = value

    cfg: _ConfigLike = DummyConfig()
    manager = ThemeManager(config_dir=tmp_path, config=cfg)
    manager.apply_theme({"accent_color": "#ff00ff"})
    assert cfg.values["theme"]["accent_color"] == "#ff00ff"
