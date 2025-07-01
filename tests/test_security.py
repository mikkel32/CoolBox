import subprocess
import platform
from types import SimpleNamespace

from src.utils.security import (
    is_firewall_enabled,
    set_firewall_enabled,
    is_defender_enabled,
    set_defender_enabled,
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
