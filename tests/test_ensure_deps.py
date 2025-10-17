import importlib
from types import ModuleType

from coolbox.ensure_deps import (
    require_package,
    ensure_customtkinter,
    ensure_psutil,
    ensure_pillow,
    ensure_pyperclip,
    ensure_rich,
    ensure_matplotlib,
    ensure_import,
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


def test_require_package_install_fallback(monkeypatch):
    calls = []

    def fake_import(name):
        if not calls:
            raise ImportError
        return ModuleType(name)

    def fake_check_call(args):
        calls.append(args)
        if len(calls) == 1:
            raise Exception("fail")

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("subprocess.check_call", fake_check_call)

    mod = require_package("missing", "1.0")
    assert isinstance(mod, ModuleType)
    assert len(calls) == 2
    assert calls[0][-1] == "missing==1.0"
    assert calls[1][-1] == "missing"


def test_ensure_customtkinter_calls_require(monkeypatch):
    called = {}

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType(name)

    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)
    monkeypatch.setattr(importlib, "import_module", fake_import)

    mod = ensure_customtkinter("5.0")
    assert mod.__name__ == "customtkinter"
    assert called == {"name": "customtkinter", "version": "5.0"}


def test_ensure_psutil_calls_require(monkeypatch):
    called = {}

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType(name)

    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)
    monkeypatch.setattr(importlib, "import_module", fake_import)

    mod = ensure_psutil("5.9.0")
    assert mod.__name__ == "psutil"
    assert called == {"name": "psutil", "version": "5.9.0"}


def test_ensure_pillow_calls_require_when_missing(monkeypatch):
    called = {}
    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType("PIL")

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType("PIL")

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)

    mod = ensure_pillow("11.0.0")
    assert mod.__name__ == "PIL"
    assert called == {"name": "Pillow", "version": "11.0.0"}


def test_ensure_pillow_no_require_when_present(monkeypatch):
    called = {}

    def fake_import(name):
        return ModuleType("PIL")

    def fake_require(name, version=None):
        called["name"] = name

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)

    mod = ensure_pillow("11.0.0")
    assert mod.__name__ == "PIL"
    assert called == {}


def test_ensure_pyperclip_calls_require(monkeypatch):
    called = {}

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType(name)

    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)
    monkeypatch.setattr(importlib, "import_module", fake_import)

    mod = ensure_pyperclip("1.8.2")
    assert mod.__name__ == "pyperclip"
    assert called == {"name": "pyperclip", "version": "1.8.2"}


def test_ensure_import_installs(monkeypatch):
    calls = {}
    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType(name)

    def fake_require(name, version=None):
        calls["name"] = name
        calls["version"] = version

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)

    mod = ensure_import("mod", package="pkg", version="1")
    assert mod.__name__ == "mod"
    assert calls == {"name": "pkg", "version": "1"}


def test_ensure_rich_calls_require(monkeypatch):
    called = {}
    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType(name)

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)

    mod = ensure_rich("13.0.0")
    assert mod.__name__ == "rich"
    assert called == {"name": "rich", "version": "13.0.0"}


def test_ensure_matplotlib_calls_require(monkeypatch):
    called = {}
    imports = {"count": 0}

    def fake_import(name):
        imports["count"] += 1
        if imports["count"] == 1:
            raise ImportError
        return ModuleType(name)

    def fake_require(name, version=None):
        called["name"] = name
        called["version"] = version
        return ModuleType(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("coolbox.ensure_deps.require_package", fake_require)

    mod = ensure_matplotlib("3.7.0")
    assert mod.__name__ == "matplotlib"
    assert called == {"name": "matplotlib", "version": "3.7.0"}
