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


def test_pip_invokes_run(monkeypatch):
    border_calls = []

    class DummyBorder:
        def __enter__(self):
            border_calls.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            border_calls.append("exit")

    run_calls = []

    def fake_run(cmd, **kw):
        run_calls.append(cmd)

    monkeypatch.setattr(setup, "NeonPulseBorder", DummyBorder)
    monkeypatch.setattr(setup, "_run", fake_run)

    setup._pip(["install", "pkg"], python=sys.executable)

    assert border_calls == []
    assert run_calls and run_calls[0][:4] == [sys.executable, "-m", "pip", "install"]


def test_pip_offline_skips(monkeypatch):
    monkeypatch.setenv("COOLBOX_OFFLINE", "1")
    importlib.reload(setup)

    run_calls = []

    def fake_run(cmd, **kw):
        run_calls.append(cmd)

    monkeypatch.setattr(setup, "_run", fake_run)
    setup._pip(["install", "pkg"], python=sys.executable)

    assert run_calls == []
