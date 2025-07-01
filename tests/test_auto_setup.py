import importlib
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
