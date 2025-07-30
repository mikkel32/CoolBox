import importlib
from types import ModuleType

from src.ensure_deps import (
    require_package,
    ensure_customtkinter,
    ensure_psutil,
    ensure_pillow,
)


def test_require_package_installs(monkeypatch):
    calls = []

    def fake_import(name):
        if name == "missing" and not calls:
            raise ImportError
        return ModuleType("missing")

    def fake_check_call(args):
        calls.append(args)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("subprocess.check_call", fake_check_call)

    mod = require_package("missing")
    assert isinstance(mod, ModuleType)
    assert calls


def test_ensure_customtkinter_calls_require(monkeypatch):
    called = {}

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    monkeypatch.setattr("src.ensure_deps.require_package", fake_require)
    mod = ensure_customtkinter("5.0")
    assert mod.__name__ == "customtkinter"
    assert called == {"name": "customtkinter", "version": "5.0"}


def test_ensure_psutil_calls_require(monkeypatch):
    called = {}

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    monkeypatch.setattr("src.ensure_deps.require_package", fake_require)
    mod = ensure_psutil("5.9.0")
    assert mod.__name__ == "psutil"
    assert called == {"name": "psutil", "version": "5.9.0"}


def test_ensure_pillow_calls_require(monkeypatch):
    called = {}

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType("PIL")

    monkeypatch.setattr("src.ensure_deps.require_package", fake_require)
    mod = ensure_pillow("10.0.0")
    assert mod.__name__ == "PIL"
    assert called == {"name": "Pillow", "version": "10.0.0"}
