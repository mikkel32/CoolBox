import importlib
import os
import sys
from types import ModuleType

import main


def test_requirements_satisfied(monkeypatch, tmp_path):
    req = tmp_path / "req.txt"
    req.write_text("foo>=1.0\n")

    fake = ModuleType("pkg_resources")
    calls = {}

    def fake_require(args):
        calls["reqs"] = args

    fake.require = fake_require
    monkeypatch.setitem(sys.modules, "pkg_resources", fake)

    importlib.reload(main)
    assert main._requirements_satisfied(req) is True
    assert calls["reqs"] == ["foo>=1.0"]


def test_requirements_satisfied_fail(monkeypatch, tmp_path):
    req = tmp_path / "req.txt"
    req.write_text("foo>=1.0\n")

    fake = ModuleType("pkg_resources")

    def fake_require(args):
        raise Exception

    fake.require = fake_require
    monkeypatch.setitem(sys.modules, "pkg_resources", fake)

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
    monkeypatch.setattr(main, "_requirements_satisfied", lambda req: False)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main._run_setup_if_needed(tmp_path)
    finally:
        os.chdir(cwd)
    assert (tmp_path / "called").read_text() == "True"
    assert (tmp_path / ".setup_done").read_text() == "x"
