import ctypes
import os
import platform
from types import SimpleNamespace

import pytest

from src.utils import security


def test_is_firewall_enabled_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, timeout=30: security.RunResult(0, "State ON\nState ON", ""),
    )
    assert security.is_firewall_enabled() is True


def test_is_firewall_enabled_macos(monkeypatch):
    monkeypatch.setattr(security, "_IS_MAC", True)
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    monkeypatch.setattr(security.firewall_utils, "is_firewall_enabled", lambda: True)
    assert security.is_firewall_enabled() is True


def test_set_firewall_enabled_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    cmds: list[list[str]] = []

    def fake_run(cmd, timeout=30):
        cmds.append(cmd)
        if cmd[:6] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]:
            return security.RunResult(0, "", "")
        return security.RunResult(0, "State ON\nState ON", "")

    monkeypatch.setattr(security, "_run", fake_run)
    res = security.set_firewall_enabled(True)
    assert res.success is True
    assert cmds[0] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]


def test_set_firewall_enabled_macos(monkeypatch):
    monkeypatch.setattr(security, "_IS_MAC", True)
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    monkeypatch.setattr(security.firewall_utils, "is_firewall_enabled", lambda: False)

    captured: dict[str, bool] = {}

    def fake_set(enabled: bool):
        captured["value"] = enabled
        return True, None

    monkeypatch.setattr(security.firewall_utils, "set_firewall_enabled", fake_set)
    res = security.set_firewall_enabled(True)
    assert res.success is True
    assert captured["value"] is True


def test_set_firewall_enabled_macos_failure(monkeypatch):
    monkeypatch.setattr(security, "_IS_MAC", True)
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    monkeypatch.setattr(security.firewall_utils, "is_firewall_enabled", lambda: False)
    monkeypatch.setattr(
        security.firewall_utils,
        "set_firewall_enabled",
        lambda enabled: (False, "permission denied"),
    )
    res = security.set_firewall_enabled(True)
    assert res.success is False
    assert "permission denied" in (res.detail or "")


def test_detect_firewall_blockers_macos(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    monkeypatch.setattr(security, "_IS_MAC", True)
    status = security.firewall_utils.FirewallStatus(
        domain=True,
        private=True,
        public=True,
        services_ok=True,
        cmdlets_available=False,
        policy_lock=False,
        third_party_firewall=False,
        services_error=None,
        error="socketfilterfw tool missing",
        mac_defaults_available=False,
        mac_socketfilterfw_available=False,
        mac_admin=False,
        mac_defaults_usable=False,
        mac_socketfilterfw_usable=False,
        mac_defaults_plist_bootstrap_supported=False,
        mac_defaults_plist_bootstrap_error="Administrator privileges required to create com.apple.alf.plist",
        mac_tool_errors=("defaults tool missing", "socketfilterfw tool missing"),
    )
    monkeypatch.setattr(security.firewall_utils, "get_firewall_status", lambda: status)
    blockers = security.detect_firewall_blockers()
    assert "macOS firewall tools missing" in blockers
    assert any("Administrator" in entry for entry in blockers)
    assert any("socketfilterfw" in entry for entry in blockers)
    assert any("defaults" in entry for entry in blockers)


def test_detect_firewall_blockers_macos_launchctl(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    monkeypatch.setattr(security, "_IS_MAC", True)
    status = security.firewall_utils.FirewallStatus(
        domain=None,
        private=None,
        public=None,
        services_ok=True,
        cmdlets_available=False,
        policy_lock=False,
        third_party_firewall=False,
        services_error=None,
        error=None,
        mac_defaults_available=True,
        mac_socketfilterfw_available=True,
        mac_admin=True,
        mac_defaults_usable=True,
        mac_socketfilterfw_usable=True,
        mac_defaults_plist_available=True,
        mac_defaults_plist_readable=True,
        mac_defaults_plist_writable=True,
        mac_defaults_plist_bootstrap_supported=True,
        mac_defaults_plist_bootstrap_error=None,
        mac_defaults_plist_damaged=True,
        mac_defaults_plist_parse_error="Invalid plist data in com.apple.alf.plist",
        mac_launchctl_available=False,
        mac_launchctl_usable=None,
        mac_launchctl_label_available=None,
        mac_launchctl_kickstart_supported=None,
        mac_launchctl_errors=("launchctl help failed",),
        mac_tool_errors=("launchctl tool missing",),
    )
    monkeypatch.setattr(security.firewall_utils, "get_firewall_status", lambda: status)
    blockers = security.detect_firewall_blockers()
    assert any("Invalid plist data" in entry for entry in blockers)
    assert "launchctl tool missing" in blockers
    assert "launchctl help failed" in blockers


def test_set_defender_realtime(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    scripts: list[str] = []

    def fake_run_ps(ps_script, timeout=30):
        scripts.append(ps_script)
        return security.RunResult(0, "", "")

    monkeypatch.setattr(security, "_run_ps", fake_run_ps)
    monkeypatch.setattr(
        security,
        "get_defender_status",
        lambda: security.DefenderStatus("RUNNING", True, True, True, True),
    )
    monkeypatch.setattr(security, "detect_defender_blockers", lambda: ())
    res = security.set_defender_realtime(True)
    assert res.success is True
    assert "DisableRealtimeMonitoring False" in scripts[0]


def test_is_admin_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    assert security.is_admin() is True


def test_is_admin_non_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    assert security.is_admin() is False


def test_ensure_admin(monkeypatch):
    monkeypatch.setattr(security, "is_admin", lambda: True)
    assert security.ensure_admin() is True

