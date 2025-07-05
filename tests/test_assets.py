from src.utils.assets import asset_path, assets_base
from src.utils import logo_paths


def test_asset_path_default(monkeypatch):
    monkeypatch.delenv("COOLBOX_ASSETS", raising=False)
    p = asset_path("images", "coolbox_logo.png")
    assert p.is_absolute()
    assert p.name == "coolbox_logo.png"
    assert assets_base() in p.parents


def test_asset_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_ASSETS", str(tmp_path))
    p = asset_path("foo", "bar.txt")
    assert p == tmp_path / "assets" / "foo" / "bar.txt"


def test_logo_paths():
    png, ico = logo_paths()
    assert png.name == 'coolbox_logo.png'
    assert ico.name == 'coolbox_logo.ico'
    assert png.exists()
    assert ico.exists()


def test_logo_env(monkeypatch, tmp_path):
    png = tmp_path / "my_logo.png"
    ico = tmp_path / "my_logo.ico"
    png.write_text("x")
    ico.write_text("y")
    monkeypatch.setenv("COOLBOX_LOGO_PNG", str(png))
    monkeypatch.setenv("COOLBOX_LOGO_ICO", str(ico))
    paths = logo_paths()
    assert paths == (png, ico)

