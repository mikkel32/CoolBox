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


def test_launch_vm_debug_missing(monkeypatch):
    called = []
    monkeypatch.setattr(shutil, "which", lambda x: None)
    monkeypatch.setattr(subprocess, "check_call", lambda args: called.append(args))
    launch_vm_debug()
    assert Path(called[0][0]).name == "run_debug.sh"
