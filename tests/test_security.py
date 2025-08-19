import platform
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.utils import security


def test_is_firewall_enabled_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_run_ex", lambda cmd, timeout=30.0: ("State ON", 0))
    assert security.is_firewall_enabled() is True


def test_set_firewall_enabled_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run_rc(cmd, timeout=30.0):
        called["cmd"] = cmd
        return 0

    monkeypatch.setattr(security, "_run_rc", fake_run_rc)
    assert security.set_firewall_enabled(True) is True
    assert called["cmd"] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]


def test_is_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_ps", lambda s, timeout=30.0: ("True", 0))
    assert security.is_defender_enabled() is True


def test_set_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_defender_cmdlets_available", lambda: True)
    monkeypatch.setattr(security, "_defender_services_ok", lambda: True)
    monkeypatch.setattr(security, "_third_party_av_present", lambda: False)
    monkeypatch.setattr(security, "_defender_tamper_on", lambda: False)
    monkeypatch.setattr(security, "_policy_lock_present", lambda: False)
    monkeypatch.setattr(security, "_managed_by_org", lambda: False)
    monkeypatch.setattr(security, "_ps", lambda s, timeout=30.0: ("", 0))
    states = [False, True]

    def fake_state():
        if states:
            return states.pop(0)
        return True

    monkeypatch.setattr(security, "is_defender_enabled", fake_state)
    monkeypatch.setattr(security.time, "sleep", lambda s: None)
    ok, err = security.set_defender_enabled(True)
    assert ok is True and err is None


def test_is_admin_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    import ctypes

    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False
    )
    assert security.is_admin() is True


def test_is_admin_unix(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(security.os, "geteuid", lambda: 0, raising=False)
    assert security.is_admin() is True


def test_ensure_admin(monkeypatch):
    monkeypatch.setattr(security, "is_admin", lambda: True)
    assert security.ensure_admin() is True


def test_launch_security_center_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    called = {}

    def fake_bg(args, **kwargs):
        called["args"] = args
        called.update(kwargs)
        return True, None

    monkeypatch.setattr(security, "run_command_background", fake_bg)
    assert security.launch_security_center() is True
    assert called["args"][0] == sys.executable

