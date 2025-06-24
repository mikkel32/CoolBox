import subprocess
import shutil
from pathlib import Path

from src.utils.vm import launch_vm_debug


def test_launch_vm_debug_vagrant(monkeypatch):
    called = []
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/vagrant" if x == "vagrant" else None)
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug()
    assert Path(called[0][0]).name == "run_vagrant.sh"


def test_launch_vm_debug_docker(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/docker" if cmd == "docker" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug()
    assert Path(called[0][0]).name == "run_devcontainer.sh"
    assert called[0][1] == "docker"


def test_launch_vm_debug_podman(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/podman" if cmd == "podman" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug()
    assert Path(called[0][0]).name == "run_devcontainer.sh"
    assert called[0][1] == "podman"


def test_launch_vm_debug_missing(monkeypatch):
    called = []
    monkeypatch.setattr(shutil, "which", lambda x: None)
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug()
    assert Path(called[0][0]).name == "run_debug.sh"


def test_launch_vm_prefer_env(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/vagrant" if cmd == "vagrant" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setenv("PREFER_VM", "vagrant")
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug()
    assert Path(called[0][0]).name == "run_vagrant.sh"


def test_launch_vm_prefer_arg(monkeypatch):
    called = []

    def which(cmd):
        return "/usr/bin/docker" if cmd == "docker" else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug(prefer="docker")
    assert Path(called[0][0]).name == "run_devcontainer.sh"


def test_launch_vm_open_code(monkeypatch):
    calls: list[str] = []

    def which(cmd: str) -> str | None:
        if cmd == "vagrant":
            return "/usr/bin/vagrant"
        if cmd == "code":
            return "/usr/bin/code"
        return None

    def popen(args):
        calls.append("code")

        class Dummy:
            def __init__(self) -> None:
                pass
        return Dummy()

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(subprocess, "check_call", lambda args: calls.append((Path(args[0]).name, args[1] if len(args) > 1 else None)))
    launch_vm_debug(open_code=True)
    assert calls[0] == "code"
    assert calls[1][0] == "run_vagrant.sh"
