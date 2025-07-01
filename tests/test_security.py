import subprocess
import platform
import os
from types import SimpleNamespace
import pytest

from src.utils.security import (
    is_firewall_enabled,
    set_firewall_enabled,
    is_defender_enabled,
    set_defender_enabled,
    is_admin,
    ensure_admin,
    require_admin,
)


def test_is_firewall_enabled_true(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    def fake_output(cmd, text=True, stderr=None):
        return "State ON"
    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_firewall_enabled() is True


def test_is_firewall_enabled_false(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    def fake_output(cmd, text=True, stderr=None):
        return "State OFF"
    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_firewall_enabled() is False


def test_set_firewall_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run(cmd, check=True, stdout=None, stderr=None):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert set_firewall_enabled(True) is True
    assert called["cmd"] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]


def test_is_firewall_enabled_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def fake_output(cmd, text=True, stderr=None):
        return "Status: active"

    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_firewall_enabled() is True


def test_set_firewall_enabled_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    called = {}

    def fake_run(cmd, check=True, stdout=None, stderr=None):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert set_firewall_enabled(False) is True
    assert called["cmd"] == ["ufw", "disable"]


def test_is_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    def fake_output(cmd, text=True, stderr=None):
        return "False"
    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_defender_enabled() is True


def test_set_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run(cmd, check=True, stdout=None, stderr=None):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert set_defender_enabled(False) is True
    assert called["cmd"] == [
        "powershell",
        "-Command",
        "Set-MpPreference -DisableRealtimeMonitoring $true",
    ]


def test_is_admin_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    import ctypes
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    assert is_admin() is True


def test_is_admin_unix(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    assert is_admin() is True


def test_ensure_admin_already_admin(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    import ctypes
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    assert ensure_admin() is True


def test_ensure_admin_unix(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 1, raising=False)
    called = {}
    monkeypatch.setattr(os, "execvp", lambda prog, args: called.update({"prog": prog, "args": args}))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    assert ensure_admin() is False
    assert called.get("prog") == "sudo"


def test_require_admin_failure(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 1, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    with pytest.raises(PermissionError):
        require_admin()
