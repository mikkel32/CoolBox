import shutil
from pathlib import Path
import asyncio

import src.utils.vm as vm
from src.utils.vm import launch_vm_debug
import pytest
import scripts.run_vm_debug as vmcli


def test_available_backends_wsl(monkeypatch):
    def which(cmd):
        return "/usr/bin/wsl" if cmd == "wsl" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm.platform, "system", lambda: "Windows")
    assert vm.available_backends() == ["wsl"]


def test_launch_vm_debug_vagrant(monkeypatch):
    called = []
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/vagrant" if x == "vagrant" else None)
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(nowait=True, detach=False) is True
    assert Path(called[0][0]).name == "run_vagrant.sh"


def test_launch_vm_debug_docker(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/docker" if cmd == "docker" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(nowait=True, detach=False) is True
    assert Path(called[0][0]).name == "run_devcontainer.sh"
    assert called[0][1] == "docker"


def test_launch_vm_debug_fallback(monkeypatch):
    calls = []

    def which(cmd):
        return "/usr/bin/docker" if cmd == "docker" else None

    def fail_call(args, **kwargs):
        calls.append(args)
        if Path(args[0]).name == "run_debug.sh":
            return "", 0
        return "", 1

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_ex", fail_call)
    assert launch_vm_debug(nowait=True, detach=False) is True
    # first attempt with docker should fail then fall back to local
    assert Path(calls[0][0]).name == "run_devcontainer.sh"
    assert Path(calls[1][0]).name == "run_debug.sh"


def test_launch_vm_debug_podman(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/podman" if cmd == "podman" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(nowait=True, detach=False) is True
    assert Path(called[0][0]).name == "run_devcontainer.sh"
    assert called[0][1] == "podman"


def test_launch_vm_debug_wsl(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/wsl" if cmd == "wsl" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm.platform, "system", lambda: "Windows")
    monkeypatch.setattr(vm.subprocess, "check_output", lambda cmd, text=True: "/mnt/c/run_debug.sh")
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(prefer="wsl", nowait=True, detach=False) is True
    assert called
    assert called[0][0] == "wsl"


def test_launch_vm_debug_missing(monkeypatch):
    called = []
    monkeypatch.setattr(shutil, "which", lambda x: None)
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(nowait=True) is True
    assert Path(called[0][0]).name == "run_debug.sh"


def test_launch_vm_prefer_env(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/vagrant" if cmd == "vagrant" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setenv("PREFER_VM", "vagrant")
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(nowait=True) is True
    assert Path(called[0][0]).name == "run_vagrant.sh"


def test_launch_vm_prefer_arg(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/docker" if cmd == "docker" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_ex", lambda args, **kw: (called.append(args) or ("", 0)))
    assert launch_vm_debug(prefer="docker", nowait=True) is True
    assert Path(called[0][0]).name == "run_devcontainer.sh"


def test_launch_vm_open_code(monkeypatch):
    calls: list[str] = []

    def which(cmd: str) -> str | None:
        if cmd == "vagrant":
            return "/usr/bin/vagrant"
        if cmd == "code":
            return "/usr/bin/code"
        return None

    def bg(args, **kwargs):
        calls.append("code")
        return True

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_background", bg)
    monkeypatch.setattr(
        vm,
        "run_command_ex",
        lambda args, **kwargs: (calls.append(
            (Path(args[0]).name, args[1] if len(args) > 1 else None)
        ) or ("", 0))
    )
    assert launch_vm_debug(open_code=True, nowait=True) is True
    assert calls[0] == "code"
    assert calls[1][0] == "run_vagrant.sh"


def test_launch_vm_open_code_missing(monkeypatch, capsys):
    """Ensure a warning is printed if VS Code is not installed."""
    def which(cmd: str) -> str | None:
        return "/usr/bin/vagrant" if cmd == "vagrant" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_background", lambda *a, **k: None)
    monkeypatch.setattr(vm, "run_command_ex", lambda *a, **k: ("", 0))
    assert launch_vm_debug(open_code=True, nowait=True) is True
    out = capsys.readouterr().out
    assert "code' command not found" in out


def test_launch_vm_detach(monkeypatch):
    called = []
    monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/vagrant" if c == "vagrant" else None)
    monkeypatch.setattr(vm, "run_command_background", lambda args, **kw: (called.append(args) or True))
    assert launch_vm_debug(detach=True) is True
    assert Path(called[0][0]).name == "run_vagrant.sh"


def test_launch_vm_debug_env(monkeypatch):
    captured = []

    def which(cmd: str) -> str | None:
        return "/usr/bin/docker" if cmd == "docker" else None

    def fake_run(cmd, *, env=None, **kwargs):
        captured.append(env)
        return "", 0

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(vm, "run_command_ex", fake_run)
    assert launch_vm_debug(port=9999, skip_deps=True, nowait=True) is True
    env = captured[0]
    assert env["DEBUG_PORT"] == "9999"
    assert env["SKIP_DEPS"] == "1"


def test_vm_cli_parse_defaults():
    args = vmcli.parse_args([])
    assert args.prefer == "auto"
    assert args.code is False
    assert args.port == 5678
    assert args.list is False
    assert args.no_wait is False
    assert args.detach is False


def test_vm_cli_main_launch(monkeypatch):
    calls = []

    def fake_launch(
        prefer=None, open_code=False, port=5678, skip_deps=False,
        print_output=True, nowait=False, detach=False
    ):
        calls.append((prefer, open_code, port, skip_deps, print_output, nowait, detach))
        return True

    monkeypatch.setattr(vmcli, "_load_launch", lambda: fake_launch)
    vmcli.main(["--prefer", "docker", "--code", "--port", "1234", "--no-wait", "--detach"])
    assert calls == [("docker", True, 1234, False, True, True, True)]


def test_vm_cli_main_auto_port(monkeypatch):
    calls = []

    def fake_launch(
        prefer=None, open_code=False, port=5678, skip_deps=False,
        print_output=True, nowait=False, detach=False
    ):
        calls.append((port, detach))
        return True

    monkeypatch.setattr(vmcli, "_load_launch", lambda: fake_launch)
    monkeypatch.setattr(vmcli, "pick_port", lambda p: 6000)
    vmcli.main(["--no-wait", "--detach"])
    assert calls == [(6000, True)]


def test_vm_cli_main_list(monkeypatch, capsys):
    monkeypatch.setattr(vmcli, "available_backends", lambda: ["docker"])
    vmcli.main(["--list"])
    out = capsys.readouterr().out
    assert "docker" in out


@pytest.mark.asyncio
async def test_async_launch_vm_debug(monkeypatch):
    called = []

    def run_in_executor(executor, func, *args):
        return func(*args)

    class FakeLoop:
        def run_in_executor(self, executor, func, *args):
            fut = asyncio.Future()
            fut.set_result(run_in_executor(executor, func, *args))
            return fut

    monkeypatch.setattr(vm.asyncio, "get_running_loop", lambda: FakeLoop())

    def fake_launch(*a, **k):
        called.append(k.get("detach", False))
        return True

    monkeypatch.setattr(vm, "launch_vm_debug", fake_launch)
    ret = await vm.async_launch_vm_debug()
    assert called == [False]
    assert ret is True
