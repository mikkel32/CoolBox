# -*- coding: utf-8 -*-
"""
Windows Firewall control utilities with deep diagnostics.
Runs netsh / PowerShell hidden. No visible consoles.

Public API:
- is_firewall_supported() -> bool
- is_firewall_enabled() -> Optional[bool]             # overall ON only if all profiles ON
- get_firewall_status() -> FirewallStatus             # rich diagnostics
- set_firewall_enabled(enabled: bool) -> (bool, str?) # toggle all profiles
- ensure_admin() -> bool
"""

from __future__ import annotations

import os
import platform
import plistlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from src.app import error_handler as eh


_IS_WINDOWS = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"

_MAC_DEFAULTS = Path("/usr/bin/defaults")
_MAC_FIREWALL_CTL = Path("/usr/libexec/ApplicationFirewall/socketfilterfw")
_MAC_DEFAULTS_DOMAIN = "/Library/Preferences/com.apple.alf"
_MAC_DEFAULTS_PLIST = Path("/Library/Preferences/com.apple.alf.plist")
_MAC_LAUNCHCTL = Path("/bin/launchctl")
_MAC_LAUNCHD_ALF_AGENT = Path("/System/Library/LaunchDaemons/com.apple.alf.agent.plist")
_MAC_LAUNCHCTL_LABEL = "system/com.apple.alf"

_MAC_DEFAULTS_FLAG_KEYS = {
    "--getstealthmode": "stealthenabled",
    "--getblockall": "blockall",
    "--getallowsigned": "allowsignedenabled",
}

_MAC_PLIST_BOOTSTRAP_TEMPLATE = {
    "globalstate": 0,
    "allowsignedenabled": 1,
    "allowdownloadsignedenabled": 1,
    "stealthenabled": 0,
    "blockall": 0,
    "firewallunload": 0,
    "version": 1,
}


@dataclass(frozen=True)
class MacFirewallTooling:
    """Represents the availability and usability of macOS firewall tooling."""

    defaults_path: Optional[Path]
    socketfilterfw_path: Optional[Path]
    defaults_usable: bool
    socketfilterfw_usable: bool
    defaults_plist_path: Optional[Path]
    defaults_plist_readable: bool
    defaults_plist_writable: bool
    defaults_plist_bootstrap_supported: bool
    defaults_plist_bootstrap_error: Optional[str]
    defaults_plist_damaged: bool
    defaults_plist_parse_error: Optional[str]
    launchctl_path: Optional[Path]
    launchctl_usable: bool
    launchctl_label_path: Optional[Path]
    launchctl_label_available: bool
    launchctl_supports_kickstart: bool
    launchctl_errors: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _mac_locate_defaults() -> Optional[Path]:
    if not _is_mac():
        return None
    if _MAC_DEFAULTS.exists():
        return _MAC_DEFAULTS
    located = shutil.which("defaults")
    if located:
        path = Path(located)
        if path.exists():
            return path
    return None


def _mac_locate_socketfilterfw() -> Optional[Path]:
    if not _is_mac():
        return None
    if _MAC_FIREWALL_CTL.exists():
        return _MAC_FIREWALL_CTL
    located = shutil.which("socketfilterfw")
    if located:
        path = Path(located)
        if path.exists():
            return path
    return None


def _mac_locate_launchctl() -> Optional[Path]:
    if not _is_mac():
        return None
    if _MAC_LAUNCHCTL.exists():
        return _MAC_LAUNCHCTL
    located = shutil.which("launchctl")
    if located:
        path = Path(located)
        if path.exists():
            return path
    return None


@lru_cache(maxsize=1)
def _mac_detect_tooling_cached() -> MacFirewallTooling:
    if not _is_mac():
        return MacFirewallTooling(
            defaults_path=None,
            socketfilterfw_path=None,
            defaults_usable=False,
            socketfilterfw_usable=False,
            defaults_plist_path=None,
            defaults_plist_readable=False,
            defaults_plist_writable=False,
            defaults_plist_bootstrap_supported=False,
            defaults_plist_bootstrap_error="Not macOS",
            defaults_plist_damaged=False,
            defaults_plist_parse_error="Not macOS",
            launchctl_path=None,
            launchctl_usable=False,
            launchctl_label_path=None,
            launchctl_label_available=False,
            launchctl_supports_kickstart=False,
            launchctl_errors=("Not macOS",),
            errors=("Not macOS",),
        )

    errors: list[str] = []
    launchctl_errors: list[str] = []

    defaults_path = _mac_locate_defaults()
    defaults_usable = False
    if defaults_path is None:
        errors.append("defaults tool missing")
    else:
        if os.access(defaults_path, os.X_OK):
            defaults_usable = True
        else:
            errors.append("defaults tool not executable")

    socket_path = _mac_locate_socketfilterfw()
    socket_usable = False
    if socket_path is None:
        errors.append("socketfilterfw tool missing")
    else:
        if os.access(socket_path, os.X_OK):
            socket_usable = True
        else:
            errors.append("socketfilterfw tool not executable")

    plist_path = _MAC_DEFAULTS_PLIST if _MAC_DEFAULTS_PLIST.exists() else None
    plist_readable = False
    plist_writable = False
    plist_damaged = False
    plist_parse_error: Optional[str] = None
    if plist_path is None:
        errors.append("com.apple.alf.plist missing")
    else:
        plist_readable = os.access(plist_path, os.R_OK)
        if not plist_readable:
            errors.append("com.apple.alf.plist not readable")
        plist_writable = os.access(plist_path, os.W_OK)
        if not plist_writable:
            errors.append("com.apple.alf.plist not writable")
        plist_data, plist_err = _mac_defaults_plist_cached()
        if plist_err:
            if "Invalid plist data" in plist_err or plist_err.startswith("Failed to read"):
                plist_damaged = True
                plist_parse_error = plist_err
            errors.append(plist_err)
        elif plist_data is None:
            plist_parse_error = f"{_MAC_DEFAULTS_PLIST.name} unavailable"
            errors.append(plist_parse_error)

    bootstrap_supported = False
    bootstrap_error: Optional[str] = None
    if plist_path is not None:
        bootstrap_supported = True
    else:
        parent = _MAC_DEFAULTS_PLIST.parent
        try:
            admin = ensure_admin()
        except Exception as exc:
            admin = False
            bootstrap_error = f"Failed to determine admin privileges: {exc}"
        if not admin:
            bootstrap_error = (
                bootstrap_error
                or "Administrator privileges required to create com.apple.alf.plist"
            )
        else:
            try:
                check_path = parent
                while not check_path.exists() and check_path.parent != check_path:
                    check_path = check_path.parent
                if os.access(check_path, os.W_OK):
                    bootstrap_supported = True
                else:
                    bootstrap_error = (
                        f"Permission denied creating {parent}"
                        if check_path == parent
                        else f"Permission denied writing {check_path}"
                    )
            except PermissionError:
                bootstrap_error = f"Permission denied inspecting {parent}"
            except Exception as exc:
                bootstrap_error = f"Failed to inspect {parent}: {exc}"
    if bootstrap_error:
        errors.append(bootstrap_error)

    launchctl_path = _mac_locate_launchctl()
    launchctl_usable = False
    if launchctl_path is None:
        launchctl_errors.append("launchctl tool missing")
    else:
        if os.access(launchctl_path, os.X_OK):
            launchctl_usable = True
        else:
            launchctl_errors.append("launchctl tool not executable")

    launchctl_label_path = (
        _MAC_LAUNCHD_ALF_AGENT if _MAC_LAUNCHD_ALF_AGENT.exists() else None
    )
    launchctl_label_available = launchctl_label_path is not None
    if not launchctl_label_available:
        launchctl_errors.append("com.apple.alf.agent launchd plist missing")
    else:
        assert launchctl_label_path is not None
        if not os.access(launchctl_label_path, os.R_OK):
            launchctl_errors.append("com.apple.alf.agent launchd plist not readable")

    launchctl_supports_kickstart = False
    if launchctl_usable:
        out, rc = _run_ex([launchctl_path.as_posix(), "help"], timeout=3.0)
        if rc == 0:
            launchctl_supports_kickstart = "kickstart" in out.lower()
        else:
            launchctl_errors.append(out or "launchctl help failed")

    errors.extend(launchctl_errors)
    deduped_errors = tuple(dict.fromkeys(errors))
    deduped_launchctl_errors = tuple(dict.fromkeys(launchctl_errors))

    return MacFirewallTooling(
        defaults_path=defaults_path,
        socketfilterfw_path=socket_path,
        defaults_usable=defaults_usable,
        socketfilterfw_usable=socket_usable,
        defaults_plist_path=plist_path,
        defaults_plist_readable=plist_readable,
        defaults_plist_writable=plist_writable,
        defaults_plist_bootstrap_supported=bootstrap_supported,
        defaults_plist_bootstrap_error=bootstrap_error,
        defaults_plist_damaged=plist_damaged,
        defaults_plist_parse_error=plist_parse_error,
        launchctl_path=launchctl_path,
        launchctl_usable=launchctl_usable,
        launchctl_label_path=launchctl_label_path,
        launchctl_label_available=launchctl_label_available,
        launchctl_supports_kickstart=launchctl_supports_kickstart,
        launchctl_errors=deduped_launchctl_errors,
        errors=deduped_errors,
    )


def _mac_tooling(refresh: bool = False) -> MacFirewallTooling:
    if refresh:
        _mac_detect_tooling_cached.cache_clear()
        _mac_defaults_plist_cached.cache_clear()
    return _mac_detect_tooling_cached()


@lru_cache(maxsize=1)
def _mac_defaults_plist_cached() -> Tuple[Optional[dict], Optional[str]]:
    if not _is_mac():
        return None, "Not macOS"
    path = _MAC_DEFAULTS_PLIST
    if not path.exists():
        return None, f"{path.name} missing"
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except PermissionError:
        return None, f"Permission denied reading {path}"
    except (plistlib.InvalidFileException, ValueError) as exc:
        return None, f"Invalid plist data in {path.name}: {exc}"
    except Exception as exc:
        return None, f"Failed to read {path.name}: {exc}"
    return data, None


def _mac_defaults_plist(refresh: bool = False) -> Tuple[Optional[dict], Optional[str]]:
    if refresh:
        _mac_defaults_plist_cached.cache_clear()
    return _mac_defaults_plist_cached()


def _mac_defaults_plist_value(key: str) -> Tuple[Optional[int], Optional[str]]:
    data, err = _mac_defaults_plist()
    if err:
        return None, err
    if data is None:
        return None, f"{_MAC_DEFAULTS_PLIST.name} unavailable"
    if key not in data:
        return None, f"{key} missing in {_MAC_DEFAULTS_PLIST.name}"
    raw = data.get(key)
    try:
        if isinstance(raw, bool):
            return (1 if raw else 0), None
        if isinstance(raw, (int, float)):
            return int(raw), None
        if raw is None:
            return None, f"{key} missing in {_MAC_DEFAULTS_PLIST.name}"
        text = str(raw).strip()
        if not text:
            return None, f"Unexpected plist value for {key}: !empty!"
        return int(text), None
    except (TypeError, ValueError):
        return None, f"Unexpected plist value for {key}: {raw!r}"


def _mac_defaults_plist_bootstrap(initial: Optional[dict[str, int]] = None) -> Optional[str]:
    if not _is_mac():
        return "Not macOS"
    path = _MAC_DEFAULTS_PLIST
    if path.exists():
        return None
    if not ensure_admin():
        return "Administrator privileges required to create com.apple.alf.plist"
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return f"Permission denied creating {parent}"
    except Exception as exc:
        return f"Failed to create {parent}: {exc}"
    payload = dict(_MAC_PLIST_BOOTSTRAP_TEMPLATE)
    if initial:
        for key, value in initial.items():
            try:
                payload[key] = int(value)
            except (TypeError, ValueError):
                payload[key] = 0
    try:
        blob = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
    except Exception as exc:
        return f"Failed to encode com.apple.alf.plist: {exc}"
    try:
        with path.open("wb") as fh:
            fh.write(blob)
    except PermissionError:
        return f"Permission denied writing {path}"
    except Exception as exc:
        return f"Failed to write com.apple.alf.plist: {exc}"
    try:
        os.chmod(path, 0o644)
    except Exception:
        pass
    _mac_defaults_plist(refresh=True)
    _mac_tooling(refresh=True)
    return None


def _mac_defaults_plist_write(
    key: str,
    value: int,
    tooling: Optional[MacFirewallTooling] = None,
) -> Optional[str]:
    if not _is_mac():
        return "Not macOS"
    path = _MAC_DEFAULTS_PLIST
    if not path.exists():
        bootstrap_err = _mac_defaults_plist_bootstrap({key: int(value)})
        if bootstrap_err:
            return bootstrap_err
        _mac_tooling(refresh=True)
        return None
    try:
        original_mode = path.stat().st_mode
    except (FileNotFoundError, PermissionError):
        original_mode = None
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except FileNotFoundError:
        return f"{path.name} missing"
    except PermissionError:
        return f"Permission denied reading {path}"
    except (plistlib.InvalidFileException, ValueError) as exc:
        parse_error = f"Invalid plist data in {path.name}: {exc}"
        tooling = tooling or _mac_tooling()
        if tooling.defaults_plist_bootstrap_supported:
            bootstrap_err = _mac_defaults_plist_bootstrap({key: int(value)})
            if bootstrap_err:
                return f"{parse_error} | {bootstrap_err}"
            _mac_tooling(refresh=True)
            return None
        return parse_error
    except Exception as exc:
        return f"Failed to read {path.name}: {exc}"
    try:
        snapshot = dict(data)
    except TypeError:
        snapshot = {}
    snapshot[key] = int(value)
    try:
        payload = plistlib.dumps(snapshot, fmt=plistlib.FMT_BINARY)
    except Exception as exc:
        return f"Failed to encode {path.name}: {exc}"
    try:
        with path.open("wb") as fh:
            fh.write(payload)
    except PermissionError:
        return f"Permission denied writing {path}"
    except Exception as exc:
        return f"Failed to write {path.name}: {exc}"
    if original_mode is not None:
        try:
            os.chmod(path, original_mode)
        except PermissionError:
            pass
        except Exception:
            pass
    _mac_defaults_plist(refresh=True)
    _mac_tooling(refresh=True)
    return None


def _mac_defaults_path() -> Optional[Path]:
    if not _is_mac():
        return None
    return _mac_tooling().defaults_path


def _mac_socketfilterfw_path() -> Optional[Path]:
    if not _is_mac():
        return None
    return _mac_tooling().socketfilterfw_path


def _mac_defaults_read_int(
    key: str,
    tooling: Optional[MacFirewallTooling] = None,
) -> Tuple[Optional[int], Optional[str]]:
    if not _is_mac():
        return None, "Not macOS"
    tooling = tooling or _mac_tooling()
    errors: list[str] = []
    value: Optional[int] = None

    defaults = tooling.defaults_path
    if defaults is None:
        errors.append("defaults tool missing")
    elif not tooling.defaults_usable:
        errors.append("defaults tool not executable")
    else:
        out, rc = _run_ex(
            [
                defaults.as_posix(),
                "read",
                _MAC_DEFAULTS_DOMAIN,
                key,
            ],
            timeout=5.0,
        )
        if rc == 0:
            match = re.search(r"(-?\d+)", out)
            if match:
                try:
                    value = int(match.group(1))
                except ValueError:
                    errors.append(
                        f"Unexpected defaults output for {key}: {out.strip() or '!empty!'}"
                    )
            else:
                errors.append(
                    f"Unexpected defaults output for {key}: {out.strip() or '!empty!'}"
                )
        else:
            errors.append(out or f"defaults read {key} failed")

    if value is None:
        plist_value, plist_err = _mac_defaults_plist_value(key)
        if plist_err:
            errors.append(plist_err)
        else:
            value = plist_value

    if value is not None:
        return value, None

    deduped = " | ".join(dict.fromkeys(err for err in errors if err))
    return None, deduped or f"{key} unavailable"


def _mac_defaults_write_int(
    key: str,
    value: int,
    tooling: Optional[MacFirewallTooling] = None,
) -> Optional[str]:
    if not _is_mac():
        return "Not macOS"
    tooling = tooling or _mac_tooling()
    errors: list[str] = []
    defaults = tooling.defaults_path
    if defaults is None:
        errors.append("defaults tool missing")
    elif not tooling.defaults_usable:
        errors.append("defaults tool not executable")
    else:
        out, rc = _run_ex(
            [
                defaults.as_posix(),
                "write",
                _MAC_DEFAULTS_DOMAIN,
                key,
                "-int",
                str(int(value)),
            ],
            timeout=5.0,
        )
        if rc == 0:
            _mac_defaults_plist(refresh=True)
            _mac_tooling(refresh=True)
            return None
        errors.append(out or f"defaults write {key} failed")

    plist_err = _mac_defaults_plist_write(key, int(value), tooling)
    if plist_err is None:
        return None
    errors.append(plist_err)

    deduped = " | ".join(dict.fromkeys(err for err in errors if err))
    return deduped or f"Failed to update {key}"


def _is_windows() -> bool:
    return _IS_WINDOWS or platform.system() == "Windows"


def _is_mac() -> bool:
    return _IS_MAC or platform.system() == "Darwin"

# ------------------------------- admin --------------------------------------


def ensure_admin() -> bool:
    if _is_mac():
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    if not _is_windows():
        return False
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        return bool(windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

# ------------------------ hidden process helpers ----------------------------


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _admin_error(text: str) -> Optional[str]:
    low = text.lower()
    if "access is denied" in low or "requested operation requires elevation" in low:
        return "AccessDenied: administrator privileges required"
    return None


def _run_ex(cmd: list[str], timeout: float = 30.0) -> Tuple[str, int]:
    try:
        cp = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            creationflags=_no_window_flags(),
            shell=False,
        )
        out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
        err = _admin_error(out)
        if err:
            return err, int(cp.returncode) if cp.returncode else -1
        if cp.returncode and not out.strip():
            return f"{' '.join(cmd)} exited with code {cp.returncode}", int(cp.returncode)
        return out.strip(), int(cp.returncode)
    except subprocess.TimeoutExpired as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return f"TimeoutExpired: {' '.join(cmd)} timed out", -1
    except FileNotFoundError as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return f"FileNotFoundError: {cmd[0]} not found", -1
    except Exception as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return f"{type(e).__name__}: {e} (while running {' '.join(cmd)})", -1


def _mac_parse_bool(text: str) -> Optional[bool]:
    low = text.strip().lower()
    if not low:
        return None
    if any(token in low for token in ("enabled", "on", "true", "yes")):
        return True
    if any(token in low for token in ("disabled", "off", "false", "no")):
        return False
    match = re.search(r"(-?\d+)", low)
    if match:
        try:
            return int(match.group(1)) != 0
        except ValueError:
            return None
    return None


def _mac_firewall_global_state(
    tooling: Optional[MacFirewallTooling] = None,
) -> Tuple[Optional[bool], Optional[int], Optional[str]]:
    """Return (enabled, numeric_state, error) for the macOS firewall."""

    if not _is_mac():
        return None, None, "Not macOS"

    tooling = tooling or _mac_tooling()

    errors: list[str] = []
    enabled: Optional[bool] = None
    numeric: Optional[int] = None

    defaults_tool = tooling.defaults_path if tooling.defaults_usable else None
    socket_tool = tooling.socketfilterfw_path if tooling.socketfilterfw_usable else None

    if defaults_tool is not None:
        numeric_value, defaults_err = _mac_defaults_read_int("globalstate", tooling)
        if defaults_err:
            errors.append(defaults_err)
        else:
            numeric = numeric_value
            enabled = numeric_value >= 1
    else:
        if tooling.defaults_path is None:
            errors.append("defaults tool missing")
        elif not tooling.defaults_usable:
            errors.append("defaults tool not executable")

    if (enabled is None or numeric is None) and socket_tool is not None:
        out, rc = _run_ex([
            socket_tool.as_posix(),
            "--getglobalstate",
        ], timeout=5.0)
        if rc == 0:
            parsed_bool = _mac_parse_bool(out)
            if enabled is None:
                enabled = parsed_bool
            if numeric is None:
                match = re.search(r"state\s*=\s*(\d+)", out, flags=re.IGNORECASE)
                if match:
                    try:
                        numeric = int(match.group(1))
                    except ValueError:
                        numeric = 1 if parsed_bool else 0 if parsed_bool is False else None
                elif parsed_bool is not None:
                    numeric = 1 if parsed_bool else 0
        else:
            errors.append(out or "socketfilterfw --getglobalstate failed")
    elif enabled is None or numeric is None:
        if tooling.socketfilterfw_path is None:
            errors.append("socketfilterfw tool missing")
        elif not tooling.socketfilterfw_usable:
            errors.append("socketfilterfw tool not executable")

    error = " | ".join(dict.fromkeys(e for e in errors if e)) if errors else None
    return enabled, numeric, error


def _mac_query_socketfilterfw(flag: str) -> Tuple[Optional[bool], Optional[str]]:
    if not _is_mac():
        return None, "Not macOS"
    tooling = _mac_tooling()
    errors: list[str] = []

    tool = tooling.socketfilterfw_path if tooling.socketfilterfw_usable else None
    if tool is not None:
        out, rc = _run_ex([tool.as_posix(), flag], timeout=5.0)
        if rc == 0:
            parsed = _mac_parse_bool(out)
            if parsed is not None:
                return parsed, None
            errors.append(f"Unexpected output for {flag}: {out.strip() or '!empty!'}")
        else:
            errors.append(out or f"socketfilterfw {flag} failed")
    else:
        if tooling.socketfilterfw_path is None:
            errors.append("socketfilterfw tool missing")
        else:
            errors.append("socketfilterfw tool not executable")

    defaults_key = _MAC_DEFAULTS_FLAG_KEYS.get(flag)
    if defaults_key:
        numeric, defaults_err = _mac_defaults_read_int(defaults_key, tooling)
        if defaults_err:
            errors.append(defaults_err)
        else:
            if numeric is not None:
                return (numeric != 0), None

    error = " | ".join(dict.fromkeys(err for err in errors if err)) if errors else None
    return None, error


def _mac_launchctl_refresh(
    tooling: Optional[MacFirewallTooling] = None,
) -> Optional[str]:
    if not _is_mac():
        return "Not macOS"
    tooling = tooling or _mac_tooling()
    if not ensure_admin():
        return "Administrator privileges required for launchctl refresh"
    path = tooling.launchctl_path
    if path is None:
        return "launchctl tool missing"
    if not tooling.launchctl_usable:
        return "launchctl tool not executable"
    if not path.exists():
        return "launchctl tool missing"
    if not os.access(path, os.X_OK):
        return "launchctl tool not executable"
    label = _MAC_LAUNCHCTL_LABEL
    out, rc = _run_ex([path.as_posix(), "kickstart", "-k", label], timeout=10.0)
    if rc == 0:
        return None
    errors = [out or "launchctl kickstart failed"]
    label_path = (
        tooling.launchctl_label_path if tooling.launchctl_label_available else None
    )
    if label_path is not None:
        unload_cmd = [path.as_posix(), "unload", label_path.as_posix()]
        out_unload, rc_unload = _run_ex(unload_cmd, timeout=10.0)
        if rc_unload not in (0, -1):
            errors.append(out_unload or "launchctl unload failed")
        load_cmd = [path.as_posix(), "load", label_path.as_posix()]
        out_load, rc_load = _run_ex(load_cmd, timeout=10.0)
        if rc_load == 0:
            return None
        errors.append(out_load or "launchctl load failed")
    detail = " | ".join(dict.fromkeys(err for err in errors if err))
    return detail or "Failed to refresh launchctl"


def _mac_set_firewall_enabled(enabled: bool) -> Tuple[bool, Optional[str]]:
    if not _is_mac():
        return False, "Not macOS"
    tooling = _mac_tooling()
    has_socket_tool = tooling.socketfilterfw_usable and tooling.socketfilterfw_path is not None
    has_defaults_cli = tooling.defaults_usable and tooling.defaults_path is not None
    has_defaults_plist = (
        tooling.defaults_plist_path is not None
        or tooling.defaults_plist_bootstrap_supported
    )
    if not (has_socket_tool or has_defaults_cli or has_defaults_plist):
        detail = "macOS firewall tooling unavailable (defaults/socketfilterfw missing or unusable)"
        if tooling.errors:
            detail = f"{detail}: {' | '.join(tooling.errors)}"
        return False, detail
    if not ensure_admin():
        return False, "Administrator privileges (root) are required to modify the macOS firewall."
    tool = tooling.socketfilterfw_path if tooling.socketfilterfw_usable else None
    state = "on" if enabled else "off"
    attempt_errors: list[str] = []
    success = False

    used_defaults = False
    if tool is not None:
        out, rc = _run_ex([
            tool.as_posix(),
            "--setglobalstate",
            state,
        ], timeout=10.0)
        if rc == 0:
            success = True
        else:
            attempt_errors.append(out or "socketfilterfw --setglobalstate failed")
    else:
        if tooling.socketfilterfw_path is None:
            attempt_errors.append("socketfilterfw tool missing")
        elif not tooling.socketfilterfw_usable:
            attempt_errors.append("socketfilterfw tool not executable")

    if not success and (has_defaults_cli or has_defaults_plist):
        target_value = 1 if enabled else 0
        defaults_err = _mac_defaults_write_int("globalstate", target_value, tooling)
        if defaults_err:
            attempt_errors.append(defaults_err)
        else:
            success = True
            used_defaults = True

    if not success:
        detail = " | ".join(dict.fromkeys(err for err in attempt_errors if err))
        if not detail:
            detail = "Failed to set macOS firewall state"
        return False, detail

    refreshed_tooling = _mac_tooling(refresh=True)
    refresh_warning: Optional[str] = None
    if used_defaults and refreshed_tooling.launchctl_path is not None:
        refresh_warning = _mac_launchctl_refresh(refreshed_tooling)
    verify, _, verify_err = _mac_firewall_global_state(refreshed_tooling)
    if verify is None:
        return False, verify_err or "Unable to verify firewall state"
    if verify != enabled:
        return False, "Firewall state mismatch after apply"
    if refresh_warning in (None, "Not macOS"):
        return True, None
    return True, refresh_warning


def _ps_path_x64() -> str:
    root = os.environ.get("SystemRoot", r"C:\\Windows")
    # Prefer 64-bit PowerShell even from 32-bit host
    if platform.machine().endswith("64") and "PROGRAMFILES(X86)" in os.environ:
        p = Path(root) / "Sysnative" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if p.exists():
            return str(p)
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


_PS_BASE = [
    _ps_path_x64(),
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-Command",
]


def _ps(script: str, timeout: float = 30.0) -> Tuple[str, int]:
    """Run PowerShell hidden with -ErrorAction Stop. Never raises."""
    if platform.system() != "Windows":
        return "Not Windows", -1
    cmd = "$ErrorActionPreference='Stop';" + script
    try:
        cp = subprocess.run(
            _PS_BASE + [cmd],
            text=True,
            capture_output=True,
            timeout=timeout,
            creationflags=_no_window_flags(),
            shell=False,
        )
        out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
        err = _admin_error(out)
        if err:
            return err, int(cp.returncode) if cp.returncode else -1
        if cp.returncode and not out.strip():
            return f"PowerShell exited with code {cp.returncode}", int(cp.returncode)
        return out.strip(), int(cp.returncode)
    except subprocess.TimeoutExpired as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return "TimeoutExpired: PowerShell timed out", -1
    except FileNotFoundError as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return "FileNotFoundError: PowerShell not found", -1
    except Exception as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return f"{type(e).__name__}: {e}", -1

# ------------------------------ internals -----------------------------------


def _services_ok() -> tuple[bool, Optional[str]]:
    """
    Ensure core services (BFE, MpsSvc) are running.
    Returns (ok, err_text).
    """
    admin = ensure_admin()
    for svc in ("BFE", "mpssvc"):
        if admin:
            _ps(
                "try { "
                f"Set-Service -Name {svc} -StartupType Automatic -EA SilentlyContinue; "
                f"if ((Get-Service -Name {svc}).Status -ne 'Running') {{ Start-Service -Name {svc} -EA SilentlyContinue }} "
                "} catch {}"
            )
        out, rc = _ps(f"(Get-Service -Name {svc}).Status")
        if rc != 0 or "Running" not in out:
            return False, f"{svc} not running"
    return True, None


def _netsecurity_available() -> bool:
    out, rc = _ps("(Get-Module -ListAvailable NetSecurity) -ne $null")
    return rc == 0 and "True" in out


def _policy_lock_present() -> bool:
    # GPO path: HKLM\SOFTWARE\Policies\Microsoft\WindowsFirewall\<profile>\EnableFirewall
    ps = (
        "try { "
        "$root='HKLM:\\SOFTWARE\\Policies\\Microsoft\\WindowsFirewall';"
        "$p=Test-Path $root -PathType Container;"
        "if (-not $p) { 'False'; break } "
        "$has = @('DomainProfile','PrivateProfile','PublicProfile') | "
        "ForEach-Object { Test-Path (Join-Path $root $_) } | "
        "Where-Object { $_ } | Measure-Object | %% Count; "
        "($has -gt 0) "
        "} catch { 'False' }"
    )
    out, rc = _ps(ps)
    return rc == 0 and "True" in out


def _third_party_firewall_present() -> bool:
    return bool(third_party_firewall_names())


def third_party_firewall_names() -> tuple[str, ...]:
    """Return the registered third-party firewalls reported by SecurityCenter2."""

    ps = (
        "($p=Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct -EA SilentlyContinue) | "
        "Where-Object { $_.displayName -ne $null -and $_.displayName -notlike '*Windows*' } | "
        "Select-Object -ExpandProperty displayName"
    )
    out, rc = _ps(ps)
    if rc != 0 or not out:
        return ()
    names = []
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        names.append(name)
    # Preserve order but drop duplicates
    return tuple(dict.fromkeys(names))


def _netsh_state_all() -> Tuple[Optional[bool], Optional[bool], Optional[bool], Optional[str]]:
    """
    Return per-profile states (domain, private, public). None if unknown.
    """
    out, rc = _run_ex(["netsh", "advfirewall", "show", "allprofiles"])
    if rc != 0:
        return None, None, None, out or "netsh failed"
    text = out.lower()

    def _find(section: str) -> Optional[bool]:
        # naive but robust across minor locale whitespace
        idx = text.find(section)
        if idx < 0:
            return None
        seg = text[idx: idx + 400]
        if "state" in seg:
            if "on" in seg.split("state", 1)[1][:60]:
                return True
            if "off" in seg.split("state", 1)[1][:60]:
                return False
        return None
    d = _find("domain profile")
    p = _find("private profile")
    u = _find("public profile")
    return d, p, u, None


def _get_profile_states() -> Tuple[Optional[bool], Optional[bool], Optional[bool], Optional[str]]:
    if _netsecurity_available():
        ps = "Get-NetFirewallProfile | Sort-Object Name | ForEach-Object { $_.Enabled }"
        out, rc = _ps(ps)
        if rc == 0:
            vals = [v.strip().lower() for v in out.splitlines() if v.strip()]
            # Names are Domain, Private, Public; ensure 3 items
            if len(vals) >= 3:
                def _b(x: str) -> Optional[bool]:
                    return True if x == "true" else False if x == "false" else None
                return _b(vals[0]), _b(vals[1]), _b(vals[2]), None
        return None, None, None, out or "Get-NetFirewallProfile failed"
    return _netsh_state_all()

# ----------------------------- public surface --------------------------------


@dataclass
class FirewallStatus:
    domain: Optional[bool]
    private: Optional[bool]
    public: Optional[bool]
    services_ok: bool
    cmdlets_available: bool
    policy_lock: bool
    third_party_firewall: bool
    services_error: Optional[str] = None
    error: Optional[str] = None
    third_party_names: tuple[str, ...] = ()
    stealth_mode: Optional[bool] = None
    block_all: Optional[bool] = None
    allows_signed: Optional[bool] = None
    mac_global_state: Optional[int] = None
    mac_defaults_available: Optional[bool] = None
    mac_socketfilterfw_available: Optional[bool] = None
    mac_admin: Optional[bool] = None
    mac_defaults_usable: Optional[bool] = None
    mac_socketfilterfw_usable: Optional[bool] = None
    mac_defaults_plist_available: Optional[bool] = None
    mac_defaults_plist_readable: Optional[bool] = None
    mac_defaults_plist_writable: Optional[bool] = None
    mac_defaults_plist_bootstrap_supported: Optional[bool] = None
    mac_defaults_plist_bootstrap_error: Optional[str] = None
    mac_defaults_plist_damaged: Optional[bool] = None
    mac_defaults_plist_parse_error: Optional[str] = None
    mac_launchctl_available: Optional[bool] = None
    mac_launchctl_usable: Optional[bool] = None
    mac_launchctl_label_available: Optional[bool] = None
    mac_launchctl_kickstart_supported: Optional[bool] = None
    mac_launchctl_errors: tuple[str, ...] = ()
    mac_tool_errors: tuple[str, ...] = ()


def is_firewall_supported() -> bool:
    if _is_windows():
        return True
    if _is_mac():
        tooling = _mac_tooling()
        return (
            tooling.defaults_usable
            or tooling.socketfilterfw_usable
            or (
                (tooling.defaults_plist_path is not None and tooling.defaults_plist_readable)
                or tooling.defaults_plist_bootstrap_supported
            )
        )
    return False


def is_firewall_enabled() -> Optional[bool]:
    if _is_windows():
        d, p, u, _ = _get_profile_states()
        if any(v is None for v in (d, p, u)):
            return None
        return bool(d) and bool(p) and bool(u)
    if _is_mac():
        tooling = _mac_tooling()
        enabled, _, _ = _mac_firewall_global_state(tooling)
        return enabled
    return None


def get_firewall_status() -> FirewallStatus:
    if _is_windows():
        d, p, u, err = _get_profile_states()
        svc_ok, svc_err = _services_ok()
        return FirewallStatus(
            domain=d,
            private=p,
            public=u,
            services_ok=svc_ok,
            cmdlets_available=_netsecurity_available(),
            policy_lock=_policy_lock_present(),
            third_party_firewall=_third_party_firewall_present(),
            services_error=svc_err,
            error=err or svc_err,
            third_party_names=third_party_firewall_names(),
        )
    if _is_mac():
        tooling = _mac_tooling()
        defaults_tool = tooling.defaults_path
        socket_tool = tooling.socketfilterfw_path
        plist_tool = tooling.defaults_plist_path
        admin = ensure_admin()
        enabled, numeric_state, state_err = _mac_firewall_global_state(tooling)
        stealth, stealth_err = _mac_query_socketfilterfw("--getstealthmode")
        block_all, block_err = _mac_query_socketfilterfw("--getblockall")
        allows_signed, signed_err = _mac_query_socketfilterfw("--getallowsigned")
        errors = [state_err, stealth_err, block_err, signed_err]
        if admin is False:
            errors.append("Administrator privileges required for firewall changes")
        if not tooling.defaults_usable:
            if defaults_tool is None:
                errors.append("defaults tool missing")
            else:
                errors.append("defaults tool not executable")
        if not tooling.socketfilterfw_usable:
            if socket_tool is None:
                errors.append("socketfilterfw tool missing")
            else:
                errors.append("socketfilterfw tool not executable")
        errors.extend(tooling.errors)
        error_text = " | ".join(dict.fromkeys(e for e in errors if e)) if any(errors) else None
        return FirewallStatus(
            domain=enabled,
            private=enabled,
            public=enabled,
            services_ok=True,
            cmdlets_available=False,
            policy_lock=False,
            third_party_firewall=False,
            services_error=None,
            error=error_text,
            third_party_names=(),
            stealth_mode=stealth,
            block_all=block_all,
            allows_signed=allows_signed,
            mac_global_state=numeric_state,
            mac_defaults_available=defaults_tool is not None,
            mac_socketfilterfw_available=socket_tool is not None,
            mac_admin=admin,
            mac_defaults_usable=tooling.defaults_usable,
            mac_socketfilterfw_usable=tooling.socketfilterfw_usable,
            mac_defaults_plist_available=plist_tool is not None,
            mac_defaults_plist_readable=tooling.defaults_plist_readable if plist_tool else False,
            mac_defaults_plist_writable=tooling.defaults_plist_writable if plist_tool else False,
            mac_defaults_plist_bootstrap_supported=tooling.defaults_plist_bootstrap_supported,
            mac_defaults_plist_bootstrap_error=tooling.defaults_plist_bootstrap_error,
            mac_defaults_plist_damaged=(
                tooling.defaults_plist_damaged if plist_tool else None
            ),
            mac_defaults_plist_parse_error=(
                tooling.defaults_plist_parse_error
                if tooling.defaults_plist_damaged
                else None
            ),
            mac_launchctl_available=tooling.launchctl_path is not None,
            mac_launchctl_usable=(
                tooling.launchctl_usable if tooling.launchctl_path is not None else False
            ),
            mac_launchctl_label_available=tooling.launchctl_label_available,
            mac_launchctl_kickstart_supported=(
                tooling.launchctl_supports_kickstart
                if tooling.launchctl_path is not None
                else False
            ),
            mac_launchctl_errors=tooling.launchctl_errors,
            mac_tool_errors=tooling.errors,
        )
    return FirewallStatus(
        None,
        None,
        None,
        False,
        False,
        False,
        False,
        None,
        "Unsupported platform",
        (),
    )


def _set_all_profiles(enabled: bool) -> Tuple[bool, str]:
    """
    Try NetSecurity first, fallback to netsh.
    """
    want = "True" if enabled else "False"
    if _netsecurity_available():
        ps = (
            f"Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled {want} -ErrorAction Stop;"
            "Get-NetFirewallProfile | Out-Null"
        )
        out, rc = _ps(ps)
        if rc == 0:
            return True, ""
        if out and "AccessDenied" in out:
            return False, out
        last_err = out or "Set-NetFirewallProfile failed"
    else:
        last_err = "NetSecurity module not present"

    # Fallback: netsh
    state = "on" if enabled else "off"
    out, rc = _run_ex(["netsh", "advfirewall", "set", "allprofiles", "state", state])
    if rc == 0:
        return True, ""
    if out and "AccessDenied" in out:
        return False, out
    return False, (out or last_err)


def set_firewall_enabled(enabled: bool) -> Tuple[bool, Optional[str]]:
    """
    Toggle all profiles. Deep verification and diagnostics.
    """
    if _is_mac():
        return _mac_set_firewall_enabled(enabled)
    if not _is_windows():
        return True, None

    if not ensure_admin():
        return False, "Administrator privileges required."

    svc_ok, svc_err = _services_ok()
    if not svc_ok:
        return False, f"Required services could not be started ({svc_err})."

    if _third_party_firewall_present():
        return False, "Another firewall is registered. Disable/uninstall it first."

    if _policy_lock_present():
        return False, "Policy lock detected (GPO/MDM). Clear WindowsFirewall policy keys or change policy."

    # Short-circuit if already desired
    cur = is_firewall_enabled()
    if cur is not None and cur == enabled:
        return True, None

    ok, err = _set_all_profiles(enabled)
    if not ok and err and "AccessDenied" in err:
        return False, err
    # Verify with retries. Profiles can lag a bit.
    for i in range(6):
        time.sleep(0.5 + 0.2 * i)
        state = is_firewall_enabled()
        if state is not None and state == enabled:
            return True, None

    if not ok:
        return False, err or "Failed to set firewall state."

    # If command reported success but state disagrees, diagnose.
    if _policy_lock_present():
        return False, "State unchanged due to policy lock (GPO/MDM)."
    svc_ok, svc_err = _services_ok()
    if not svc_ok:
        return False, f"State unchanged because {svc_err}."
    return False, "Firewall state unchanged for unknown reason."
