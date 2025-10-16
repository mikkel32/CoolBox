import importlib
import sys
import subprocess
import time
from pathlib import Path

import pytest

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
    setup.set_offline(False)

    setup._pip(["install", "pkg"], python=sys.executable)

    assert border_calls == []
    assert run_calls and run_calls[0][:4] == [sys.executable, "-m", "pip", "install"]


def test_pip_offline_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_OFFLINE", "1")
    importlib.reload(setup)

    run_calls: list[list[str]] = []
    env_calls: list[dict | None] = []

    def fake_run(cmd, env=None, **kw):
        run_calls.append(cmd)
        env_calls.append(env)

    monkeypatch.setattr(setup, "_run", fake_run)
    monkeypatch.setattr(setup, "_available_wheel_links", lambda: [str(tmp_path)])

    setup._pip(["install", "pkg"], python=sys.executable)

    assert run_calls, "pip should still run in offline mode"
    assert "--no-index" in run_calls[0]
    assert env_calls[0] is not None
    assert env_calls[0]["PIP_NO_INDEX"] == "1"


def test_cli_offline_flag(monkeypatch):
    monkeypatch.delenv("COOLBOX_OFFLINE", raising=False)
    importlib.reload(setup)
    setup.set_offline(False)
    monkeypatch.setattr(setup, "show_info", lambda: None)

    with pytest.raises(SystemExit):
        setup.main(["--offline", "info"])
    assert setup.is_offline() is True


@pytest.mark.parametrize(
    "platform, expected",
    [
        ("linux", Path("venv") / "bin" / "python"),
        ("darwin", Path("venv") / "bin" / "python"),
        ("win32", Path("venv") / "Scripts" / "python.exe"),
    ],
)
def test_venv_python_platform(monkeypatch, tmp_path, platform, expected):
    monkeypatch.setenv("COOLBOX_VENV", str(tmp_path / "venv"))
    monkeypatch.setattr(sys, "platform", platform)
    path = Path(setup._venv_python())
    assert path == (tmp_path / expected).resolve()


def test_setup_run_speed():
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "setup.py", "--help"],
        check=True,
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    duration = time.perf_counter() - start
    assert duration < 5


def test_run_timeout():
    with pytest.raises(RuntimeError):
        setup._run([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.1)


def test_config_file_overrides(monkeypatch, tmp_path):
    cfg = tmp_path / ".coolboxrc"
    cfg.write_text("{""no_anim"": true}")
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    importlib.reload(setup)
    assert setup.CONFIG.no_anim is True
