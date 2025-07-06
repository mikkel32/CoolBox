import builtins
import shutil

import scripts.run_vm_debug as rvd


def test_load_launch_without_heavy_deps(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"customtkinter", "psutil"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    launch = rvd._load_launch()
    assert callable(launch)


def test_available_backends(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/" + x if x == "docker" else None)
    backends = rvd.available_backends()
    assert backends == ["docker"]


def test_parse_defaults():
    args = rvd.parse_args([])
    assert args.prefer == "auto"
    assert args.code is False
    assert args.port == 5678
    assert args.list is False
    assert args.skip_deps is False
    assert args.quiet is False
    assert args.no_wait is False
    assert args.detach is False


def test_main_list_backends(monkeypatch, capsys):
    monkeypatch.setattr(rvd, "available_backends", lambda: ["docker", "vagrant"])
    monkeypatch.setattr(rvd, "_load_launch", lambda: lambda prefer=None, open_code=False: None)
    monkeypatch.setattr(rvd.sys, "argv", ["run_vm_debug.py", "--list"])
    rvd.main()
    out = capsys.readouterr().out.strip()
    assert out == "Available backends: docker vagrant"


def test_main_passes_port(monkeypatch):
    called = {}

    def fake_launch(prefer=None, open_code=False, port=5678, skip_deps=False, print_output=True, nowait=False, detach=False):
        called["prefer"] = prefer
        called["open_code"] = open_code
        called["port"] = port
        called["print_output"] = print_output
        called["nowait"] = nowait
        called["detach"] = detach
        return True

    monkeypatch.setattr(rvd, "_load_launch", lambda: fake_launch)
    monkeypatch.setattr(rvd.sys, "argv", ["run_vm_debug.py", "--port", "9999", "--no-wait", "--quiet"])
    rvd.main()
    assert called["port"] == 9999
    assert called["nowait"] is True
    assert called["print_output"] is False
    assert called["detach"] is False


def test_main_skip_deps(monkeypatch):
    called = {}

    def fake_launch(prefer=None, open_code=False, port=5678, skip_deps=False, print_output=True, nowait=False, detach=False):
        called["skip_deps"] = skip_deps
        called["nowait"] = nowait
        called["print_output"] = print_output
        called["detach"] = detach
        return True

    monkeypatch.setattr(rvd, "_load_launch", lambda: fake_launch)
    monkeypatch.setattr(
        rvd.sys,
        "argv",
        ["run_vm_debug.py", "--skip-deps", "--no-wait", "--quiet"],
    )
    rvd.main()
    assert called["skip_deps"] is True
    assert called["nowait"] is True
    assert called["print_output"] is False
    assert called["detach"] is False


def test_main_detach(monkeypatch):
    called = {}

    def fake_launch(prefer=None, open_code=False, port=5678, skip_deps=False, print_output=True, nowait=False, detach=False):
        called["detach"] = detach
        return True

    monkeypatch.setattr(rvd, "_load_launch", lambda: fake_launch)
    monkeypatch.setattr(rvd.sys, "argv", ["run_vm_debug.py", "--detach"])
    rvd.main()
    assert called["detach"] is True
