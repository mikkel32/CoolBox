import importlib

import setup


def test_get_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_ROOT", str(tmp_path))
    importlib.reload(setup)
    assert setup.get_root() == tmp_path


def test_locate_root_search(tmp_path):
    root = tmp_path / "project"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "requirements.txt").write_text("")
    assert setup.locate_root(sub) == root


def test_get_venv_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_VENV", str(tmp_path / "v"))
    importlib.reload(setup)
    assert setup.get_venv_dir() == tmp_path / "v"
