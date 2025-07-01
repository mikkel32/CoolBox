import importlib
import sys

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


def test_pip_uses_blue_glow(monkeypatch):
    calls = []

    class DummyBorder:
        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append("exit")

    monkeypatch.setattr(setup, "NeonPulseBorder", DummyBorder)
    monkeypatch.setattr(
        setup.subprocess,
        "check_call",
        lambda cmd, **kw: calls.append(cmd),
    )
    setup._pip(["install", "pkg"], python=sys.executable)
    assert calls[0] == "enter" and calls[-1] == "exit"
