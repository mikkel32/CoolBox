from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Optional

import src.utils.firewall as firewall


def setup_macos(
    monkeypatch,
    *,
    defaults: bool = True,
    socket: bool = True,
    admin: bool = True,
    defaults_usable: Optional[bool] = None,
    socket_usable: Optional[bool] = None,
    plist: bool = True,
    plist_readable: Optional[bool] = None,
    plist_writable: Optional[bool] = None,
    plist_path_override: Optional[Path] = None,
    plist_bootstrap_supported: Optional[bool] = None,
    plist_bootstrap_error: Optional[str] = None,
    plist_damaged: bool = False,
    plist_parse_error: Optional[str] = None,
    launchctl: bool = True,
    launchctl_usable: Optional[bool] = None,
    launchctl_label: bool = True,
    launchctl_supports_kickstart: Optional[bool] = None,
    launchctl_extra_errors: Optional[list[str]] = None,
) -> None:
    monkeypatch.setattr(firewall, "_IS_MAC", True)
    monkeypatch.setattr(firewall, "_IS_WINDOWS", False)

    plist_path = (
        plist_path_override
        if plist_path_override is not None
        else Path("/Library/Preferences/com.apple.alf.plist")
        if plist
        else None
    )
    readable = plist if plist_readable is None else plist_readable
    writable = plist if plist_writable is None else plist_writable
    bootstrap_default = True if plist else bool(admin)
    bootstrap_supported = (
        bootstrap_default if plist_bootstrap_supported is None else plist_bootstrap_supported
    )
    if (
        plist_bootstrap_error is None
        and not plist
        and not bootstrap_supported
    ):
        plist_bootstrap_error = (
            "Administrator privileges required to create com.apple.alf.plist"
            if admin is False
            else "com.apple.alf.plist bootstrap unavailable"
        )

    launchctl_path = Path("/bin/launchctl") if launchctl else None
    launchctl_is_usable = launchctl if launchctl_usable is None else launchctl_usable
    launchctl_label_path = (
        Path("/System/Library/LaunchDaemons/com.apple.alf.agent.plist")
        if launchctl_label
        else None
    )
    launchctl_support = (
        launchctl if launchctl_supports_kickstart is None else launchctl_supports_kickstart
    )

    launchctl_errors_list = [
        entry
        for entry in (
            "launchctl tool missing" if not launchctl else None,
            "launchctl tool not executable"
            if launchctl and (launchctl_is_usable is False)
            else None,
            "com.apple.alf.agent launchd plist missing"
            if launchctl_label_path is None
            else None,
        )
        if entry
    ]
    if launchctl_extra_errors:
        launchctl_errors_list.extend(launchctl_extra_errors)

    errors = [
        entry
        for entry in (
            "defaults tool missing" if not defaults else None,
            "defaults tool not executable" if defaults and (defaults_usable is False) else None,
            "socketfilterfw tool missing" if not socket else None,
            "socketfilterfw tool not executable" if socket and (socket_usable is False) else None,
            "com.apple.alf.plist missing" if not plist else None,
            "com.apple.alf.plist not readable"
            if plist and (plist_readable is False)
            else None,
            "com.apple.alf.plist not writable"
            if plist and (plist_writable is False)
            else None,
            plist_bootstrap_error,
        )
        if entry
    ]
    errors.extend(launchctl_errors_list)

    tooling = firewall.MacFirewallTooling(
        defaults_path=Path("/usr/bin/defaults") if defaults else None,
        socketfilterfw_path=Path("/usr/libexec/ApplicationFirewall/socketfilterfw") if socket else None,
        defaults_usable=defaults if defaults_usable is None else defaults_usable,
        socketfilterfw_usable=socket if socket_usable is None else socket_usable,
        defaults_plist_path=plist_path,
        defaults_plist_readable=bool(readable),
        defaults_plist_writable=bool(writable),
        defaults_plist_bootstrap_supported=bool(bootstrap_supported),
        defaults_plist_bootstrap_error=plist_bootstrap_error,
        defaults_plist_damaged=bool(plist_damaged) if plist else False,
        defaults_plist_parse_error=(
            plist_parse_error if (plist and plist_damaged) else None
        ),
        launchctl_path=launchctl_path,
        launchctl_usable=bool(launchctl_is_usable) if launchctl_path else False,
        launchctl_label_path=launchctl_label_path,
        launchctl_label_available=launchctl_label_path is not None,
        launchctl_supports_kickstart=bool(launchctl_support) if launchctl_path else False,
        launchctl_errors=tuple(dict.fromkeys(launchctl_errors_list)),
        errors=tuple(dict.fromkeys(errors)),
    )

    def fake_tooling(refresh: bool = False) -> firewall.MacFirewallTooling:
        return tooling

    monkeypatch.setattr(firewall, "_mac_tooling", fake_tooling)
    monkeypatch.setattr(firewall, "ensure_admin", lambda: admin)
    firewall._mac_defaults_plist_cached.cache_clear()
    return tooling


def test_is_firewall_supported_macos(monkeypatch):
    setup_macos(monkeypatch)
    assert firewall.is_firewall_supported() is True


def test_is_firewall_supported_macos_missing_tools(monkeypatch):
    setup_macos(monkeypatch, defaults=False, socket=False, plist=False, admin=False)
    assert firewall.is_firewall_supported() is False


def test_is_firewall_supported_macos_unusable_tools(monkeypatch):
    setup_macos(
        monkeypatch,
        defaults=True,
        socket=True,
        defaults_usable=False,
        socket_usable=False,
    )
    assert firewall.is_firewall_supported() is True


def test_is_firewall_supported_macos_plist_only(monkeypatch):
    setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=True,
        plist_path_override=Path("/tmp/com.apple.alf.plist"),
    )
    assert firewall.is_firewall_supported() is True


def test_is_firewall_supported_macos_bootstrap_only(monkeypatch):
    setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=False,
        plist_bootstrap_supported=True,
    )
    assert firewall.is_firewall_supported() is True


def test_is_firewall_enabled_macos(monkeypatch):
    setup_macos(monkeypatch)
    monkeypatch.setattr(firewall, "_mac_firewall_global_state", lambda tooling=None: (True, 1, None))
    assert firewall.is_firewall_enabled() is True


def test_is_firewall_enabled_macos_unknown(monkeypatch):
    setup_macos(monkeypatch)
    monkeypatch.setattr(firewall, "_mac_firewall_global_state", lambda tooling=None: (None, None, "boom"))
    assert firewall.is_firewall_enabled() is None


def test_get_firewall_status_macos(monkeypatch):
    tooling = setup_macos(monkeypatch)
    monkeypatch.setattr(
        firewall,
        "_mac_firewall_global_state",
        lambda tooling=None: (True, 2, None),
    )

    def fake_query(flag: str):
        mapping = {
            "--getstealthmode": (True, None),
            "--getblockall": (False, None),
            "--getallowsigned": (True, None),
        }
        return mapping.get(flag, (None, "unexpected flag"))

    monkeypatch.setattr(firewall, "_mac_query_socketfilterfw", fake_query)
    status = firewall.get_firewall_status()
    assert status.domain is True
    assert status.mac_global_state == 2
    assert status.stealth_mode is True
    assert status.block_all is False
    assert status.mac_defaults_available is True
    assert status.mac_socketfilterfw_available is True
    assert status.mac_admin is True
    assert status.mac_defaults_usable is True
    assert status.mac_socketfilterfw_usable is True
    assert status.mac_defaults_plist_available is True
    assert status.mac_defaults_plist_readable is True
    assert status.mac_defaults_plist_writable is True
    assert status.mac_defaults_plist_bootstrap_supported is True
    assert status.mac_defaults_plist_bootstrap_error is None
    assert status.mac_defaults_plist_damaged is False
    assert status.mac_defaults_plist_parse_error is None
    assert status.mac_launchctl_available is True
    assert status.mac_launchctl_usable is True
    assert status.mac_launchctl_label_available is True
    assert status.mac_launchctl_kickstart_supported is True
    assert status.mac_launchctl_errors == ()
    assert status.mac_tool_errors == tooling.errors


def test_get_firewall_status_macos_missing_tools(monkeypatch):
    tooling = setup_macos(monkeypatch, defaults=False, socket=False)
    monkeypatch.setattr(
        firewall,
        "_mac_firewall_global_state",
        lambda tooling=None: (None, None, "defaults tool missing | socketfilterfw tool missing"),
    )
    monkeypatch.setattr(
        firewall,
        "_mac_query_socketfilterfw",
        lambda flag: (None, "socketfilterfw tool missing"),
    )
    status = firewall.get_firewall_status()
    assert status.mac_defaults_available is False
    assert status.mac_socketfilterfw_available is False
    assert status.error is not None
    assert status.mac_defaults_usable is False
    assert status.mac_socketfilterfw_usable is False
    assert status.mac_defaults_plist_available is True
    assert status.mac_defaults_plist_readable is True
    assert status.mac_defaults_plist_writable is True
    assert status.mac_defaults_plist_bootstrap_supported is True
    assert status.mac_defaults_plist_bootstrap_error is None
    assert status.mac_tool_errors == tooling.errors


def test_get_firewall_status_macos_unusable_tools(monkeypatch):
    tooling = setup_macos(
        monkeypatch,
        defaults=True,
        socket=True,
        defaults_usable=False,
        socket_usable=False,
    )
    monkeypatch.setattr(
        firewall,
        "_mac_firewall_global_state",
        lambda tooling=None: (None, None, "defaults tool not executable | socketfilterfw tool not executable"),
    )
    monkeypatch.setattr(
        firewall,
        "_mac_query_socketfilterfw",
        lambda flag: (None, "socketfilterfw tool not executable"),
    )
    status = firewall.get_firewall_status()
    assert status.mac_defaults_available is True
    assert status.mac_socketfilterfw_available is True
    assert status.mac_defaults_usable is False
    assert status.mac_socketfilterfw_usable is False
    assert any("not executable" in part for part in status.mac_tool_errors)
    assert status.mac_defaults_plist_available is True
    assert status.mac_defaults_plist_readable is True
    assert status.mac_defaults_plist_writable is True
    assert status.mac_defaults_plist_bootstrap_supported is True
    assert status.mac_defaults_plist_bootstrap_error is None
    assert status.mac_tool_errors == tooling.errors


def test_get_firewall_status_macos_missing_plist(monkeypatch):
    tooling = setup_macos(monkeypatch, plist=False)
    monkeypatch.setattr(
        firewall,
        "_mac_firewall_global_state",
        lambda tooling=None: (None, None, "com.apple.alf.plist missing"),
    )
    monkeypatch.setattr(
        firewall,
        "_mac_query_socketfilterfw",
        lambda flag: (None, "com.apple.alf.plist missing"),
    )
    status = firewall.get_firewall_status()
    assert status.mac_defaults_plist_available is False
    assert status.mac_defaults_plist_readable is False
    assert status.mac_defaults_plist_writable is False
    assert status.mac_defaults_plist_bootstrap_supported is True
    assert status.mac_defaults_plist_bootstrap_error is None
    assert "com.apple.alf.plist" in (status.error or "")
    assert status.mac_tool_errors == tooling.errors


def test_set_firewall_enabled_macos(monkeypatch):
    setup_macos(monkeypatch)
    calls: list[bool] = []

    def fake_set(state: bool):
        calls.append(state)
        return True, None

    monkeypatch.setattr(firewall, "_mac_set_firewall_enabled", fake_set)
    ok, err = firewall.set_firewall_enabled(True)
    assert ok is True
    assert err is None
    assert calls == [True]


def test_set_firewall_enabled_macos_failure(monkeypatch):
    setup_macos(monkeypatch)
    monkeypatch.setattr(
        firewall,
        "_mac_set_firewall_enabled",
        lambda enabled: (False, "permission denied"),
    )
    ok, err = firewall.set_firewall_enabled(True)
    assert ok is False
    assert err == "permission denied"


def test_set_firewall_enabled_macos_requires_admin(monkeypatch):
    setup_macos(monkeypatch, admin=False)
    ok, err = firewall.set_firewall_enabled(True)
    assert ok is False
    assert "Administrator" in (err or "")


def test_set_firewall_enabled_macos_missing_socketfilterfw(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.apple.alf.plist"
    with plist_path.open("wb") as fh:
        plistlib.dump({"globalstate": 0}, fh, fmt=plistlib.FMT_BINARY)

    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()

    setup_macos(
        monkeypatch,
        socket=False,
        defaults=True,
        defaults_usable=False,
        plist=True,
        plist_path_override=plist_path,
        launchctl=False,
    )

    def fake_global_state(tooling=None):
        firewall._mac_defaults_plist_cached.cache_clear()
        value, err = firewall._mac_defaults_plist_value("globalstate")
        if err:
            return None, None, err
        return (value >= 1), value, None

    monkeypatch.setattr(firewall, "_mac_firewall_global_state", fake_global_state)

    ok, err = firewall.set_firewall_enabled(True)
    assert ok is True
    assert err is None
    with plist_path.open("rb") as fh:
        payload = plistlib.load(fh)
    assert payload["globalstate"] == 1


def test_set_firewall_enabled_macos_unusable_socketfilterfw(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.apple.alf.plist"
    with plist_path.open("wb") as fh:
        plistlib.dump({"globalstate": 0}, fh, fmt=plistlib.FMT_BINARY)

    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()

    setup_macos(
        monkeypatch,
        socket=True,
        socket_usable=False,
        defaults=True,
        defaults_usable=False,
        plist=True,
        plist_path_override=plist_path,
        launchctl=False,
    )

    def fake_global_state(tooling=None):
        firewall._mac_defaults_plist_cached.cache_clear()
        value, err = firewall._mac_defaults_plist_value("globalstate")
        if err:
            return None, None, err
        return (value >= 1), value, None

    monkeypatch.setattr(firewall, "_mac_firewall_global_state", fake_global_state)

    ok, err = firewall.set_firewall_enabled(True)
    assert ok is True
    assert err is None
    with plist_path.open("rb") as fh:
        payload = plistlib.load(fh)
    assert payload["globalstate"] == 1


def test_mac_query_socketfilterfw_defaults_fallback(monkeypatch):
    setup_macos(monkeypatch, socket=False)

    def fake_defaults_read(key: str, tooling=None):
        assert key == "stealthenabled"
        return 1, None

    monkeypatch.setattr(firewall, "_mac_defaults_read_int", fake_defaults_read)

    value, err = firewall._mac_query_socketfilterfw("--getstealthmode")
    assert value is True
    assert err is None


def test_mac_query_socketfilterfw_socket_failure_fallback(monkeypatch):
    setup_macos(monkeypatch)

    def fake_run_ex(cmd, timeout=5.0):
        if "socketfilterfw" in cmd[0]:
            return "boom", 1
        return "", 0

    seen: list[str] = []

    def fake_defaults_read(key: str, tooling=None):
        seen.append(key)
        return 0, None

    monkeypatch.setattr(firewall, "_run_ex", fake_run_ex)
    monkeypatch.setattr(firewall, "_mac_defaults_read_int", fake_defaults_read)

    value, err = firewall._mac_query_socketfilterfw("--getblockall")
    assert value is False
    assert err is None
    assert seen == ["blockall"]


def test_mac_defaults_plist_write_repairs_invalid(monkeypatch, tmp_path):
    monkeypatch.setattr(firewall, "_IS_MAC", True)
    monkeypatch.setattr(firewall, "_IS_WINDOWS", False)
    plist_path = tmp_path / "com.apple.alf.plist"
    plist_path.write_text("not-a-plist")
    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()
    firewall._mac_detect_tooling_cached.cache_clear()
    monkeypatch.setattr(firewall, "ensure_admin", lambda: True)

    recorded: dict[str, dict[str, int]] = {}

    def fake_bootstrap(initial=None):
        recorded["initial"] = dict(initial or {})
        payload = dict(firewall._MAC_PLIST_BOOTSTRAP_TEMPLATE)
        payload.update(initial or {})
        with plist_path.open("wb") as fh:
            plistlib.dump(payload, fh, fmt=plistlib.FMT_BINARY)
        firewall._mac_defaults_plist_cached.cache_clear()
        return None

    monkeypatch.setattr(firewall, "_mac_defaults_plist_bootstrap", fake_bootstrap)

    tooling = firewall.MacFirewallTooling(
        defaults_path=None,
        socketfilterfw_path=None,
        defaults_usable=False,
        socketfilterfw_usable=False,
        defaults_plist_path=plist_path,
        defaults_plist_readable=True,
        defaults_plist_writable=True,
        defaults_plist_bootstrap_supported=True,
        defaults_plist_bootstrap_error=None,
        defaults_plist_damaged=True,
        defaults_plist_parse_error="Invalid plist data",
        launchctl_path=None,
        launchctl_usable=False,
        launchctl_label_path=None,
        launchctl_label_available=False,
        launchctl_supports_kickstart=False,
        launchctl_errors=(),
        errors=(),
    )

    err = firewall._mac_defaults_plist_write("globalstate", 1, tooling)
    assert err is None
    assert recorded["initial"] == {"globalstate": 1}
    with plist_path.open("rb") as fh:
        payload = plistlib.load(fh)
    assert payload["globalstate"] == 1


def test_mac_defaults_read_int_plist_fallback(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.apple.alf.plist"
    with plist_path.open("wb") as fh:
        plistlib.dump({"globalstate": 2}, fh, fmt=plistlib.FMT_BINARY)

    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()

    setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=True,
        plist_path_override=plist_path,
    )

    value, err = firewall._mac_defaults_read_int("globalstate")
    assert value == 2
    assert err is None


def test_mac_defaults_write_int_plist_fallback(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.apple.alf.plist"
    with plist_path.open("wb") as fh:
        plistlib.dump({"globalstate": 0}, fh, fmt=plistlib.FMT_BINARY)

    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()

    setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=True,
        plist_path_override=plist_path,
    )

    err = firewall._mac_defaults_write_int("globalstate", 1)
    assert err is None

    firewall._mac_defaults_plist_cached.cache_clear()
    value, err = firewall._mac_defaults_read_int("globalstate")
    assert value == 1
    assert err is None


def test_mac_defaults_plist_bootstrap_creates_file(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.apple.alf.plist"
    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()

    setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=False,
        plist_bootstrap_supported=True,
    )

    err = firewall._mac_defaults_plist_bootstrap({"globalstate": 1})
    assert err is None
    assert plist_path.exists()

    with plist_path.open("rb") as fh:
        data = plistlib.load(fh)
    assert data["globalstate"] == 1
    assert data["allowsignedenabled"] == 1


def test_mac_set_firewall_enabled_defaults_fallback(monkeypatch):
    setup_macos(monkeypatch, socket=False, launchctl=False)

    state = {"global": 0}

    def fake_defaults_write(key: str, value: int, tooling=None):
        if key == "globalstate":
            state["global"] = value
            return None
        return "unexpected key"

    def fake_defaults_read(key: str, tooling=None):
        if key == "globalstate":
            return state["global"], None
        return None, "missing key"

    monkeypatch.setattr(firewall, "_mac_defaults_write_int", fake_defaults_write)
    monkeypatch.setattr(firewall, "_mac_defaults_read_int", fake_defaults_read)

    ok, err = firewall.set_firewall_enabled(True)
    assert ok is True
    assert err is None
    assert state["global"] == 1


def test_mac_set_firewall_enabled_launchctl_refresh(monkeypatch):
    state = {"value": 0}
    tooling = setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=True,
    )

    def fake_defaults_write(key: str, value: int, tooling_override=None):
        assert key == "globalstate"
        state["value"] = int(value)
        return None

    def fake_global_state(tooling_override=None):
        enabled = state["value"] >= 1
        return enabled, state["value"], None

    refresh_calls: list[Optional[firewall.MacFirewallTooling]] = []

    def fake_launchctl_refresh(tooling_override=None):
        refresh_calls.append(tooling_override)
        return "launchctl kickstart failed"

    monkeypatch.setattr(firewall, "_mac_defaults_write_int", fake_defaults_write)
    monkeypatch.setattr(firewall, "_mac_firewall_global_state", fake_global_state)
    monkeypatch.setattr(firewall, "_mac_launchctl_refresh", fake_launchctl_refresh)

    ok, err = firewall._mac_set_firewall_enabled(True)
    assert ok is True
    assert err == "launchctl kickstart failed"
    assert state["value"] == 1
    assert refresh_calls == [tooling]


def test_mac_set_firewall_enabled_bootstrap(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.apple.alf.plist"
    monkeypatch.setattr(firewall, "_MAC_DEFAULTS_PLIST", plist_path)
    firewall._mac_defaults_plist_cached.cache_clear()

    setup_macos(
        monkeypatch,
        defaults=False,
        socket=False,
        plist=False,
        plist_bootstrap_supported=True,
        launchctl=False,
    )

    def fake_global_state(tooling=None):
        firewall._mac_defaults_plist_cached.cache_clear()
        value, err = firewall._mac_defaults_plist_value("globalstate")
        if err:
            return None, None, err
        return (value >= 1), value, None

    monkeypatch.setattr(firewall, "_mac_firewall_global_state", fake_global_state)

    ok, err = firewall.set_firewall_enabled(True)
    assert ok is True
    assert err is None
    assert plist_path.exists()
    with plist_path.open("rb") as fh:
        payload = plistlib.load(fh)
    assert payload["globalstate"] == 1


def test_mac_set_firewall_enabled_reports_aggregate_errors(monkeypatch):
    setup_macos(monkeypatch)

    def fake_run_ex(cmd, timeout=10.0):
        if "socketfilterfw" in cmd[0]:
            return "socket failure", 1
        return "", 0

    def fake_defaults_write(key: str, value: int, tooling=None):
        return "defaults write globalstate failed"

    monkeypatch.setattr(firewall, "_run_ex", fake_run_ex)
    monkeypatch.setattr(firewall, "_mac_defaults_write_int", fake_defaults_write)

    ok, err = firewall.set_firewall_enabled(True)
    assert ok is False
    assert "socket failure" in (err or "")
    assert "defaults write globalstate failed" in (err or "")
