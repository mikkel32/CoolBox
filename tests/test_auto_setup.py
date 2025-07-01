import importlib
import os
import sys
from types import ModuleType
from importlib import metadata

import main


def test_requirements_satisfied(monkeypatch, tmp_path):
    req = tmp_path / "req.txt"
    req.write_text("foo>=1.0\n")

    calls = {}

    def fake_version(name: str) -> str:
        calls["pkg"] = name
        return "1.2"

    monkeypatch.setattr(metadata, "version", fake_version)
    importlib.reload(main)
    assert main._requirements_satisfied(req) is True
    assert calls["pkg"] == "foo"


def test_requirements_satisfied_fail(monkeypatch, tmp_path):
    req = tmp_path / "req.txt"
    req.write_text("foo>=1.0\n")

    def fake_version(name: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", fake_version)
    importlib.reload(main)
    assert main._requirements_satisfied(req) is False


def test_run_setup_if_needed_imports_setup(monkeypatch, tmp_path):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text(
        """
from pathlib import Path
def show_setup_banner():
    pass
def check_python_version():
    pass
def install(skip_update=False):
    Path('called').write_text(str(skip_update))
"""
    )
    (tmp_path / "requirements.txt").write_text("")
    monkeypatch.setattr(main, "_compute_setup_state", lambda root: "x")
    monkeypatch.setattr(main, "_missing_requirements", lambda req: ["foo"])
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main._run_setup_if_needed(tmp_path)
    finally:
        os.chdir(cwd)
    assert (tmp_path / "called").read_text() == "True"
    assert (tmp_path / ".setup_done").read_text() == "x"
