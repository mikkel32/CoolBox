# -*- coding: utf-8 -*-
"""
Windows Defender control utilities with deep diagnostics.
Runs 64-bit PowerShell hidden. No visible consoles.

Public API:
- is_defender_supported() -> bool
- is_defender_enabled() -> Optional[bool]
- get_defender_status() -> DefenderStatus
- set_defender_enabled(enabled: bool) -> tuple[bool, Optional[str]]
- ensure_admin() -> bool
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.app import error_handler as eh

# ------------------------------- admin --------------------------------------


def ensure_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        return bool(windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

# ------------------------ hidden PowerShell runner --------------------------


def _ps_path_x64() -> str:
    """Prefer 64-bit PowerShell even from 32-bit Python."""
    root = os.environ.get("SystemRoot", r"C:\\Windows")
    if platform.machine().endswith("64") and "PROGRAMFILES(X86)" in os.environ:
        p = Path(root) / "Sysnative" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if p.exists():
            return str(p)
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _no_window_flags() -> int:
    # CREATE_NO_WINDOW exists on Windows python; guard for type checkers.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _admin_error(text: str) -> Optional[str]:
    low = text.lower()
    if "access is denied" in low or "requested operation requires elevation" in low:
        return "AccessDenied: administrator privileges required"
    return None


_PS_BASE = [
    _ps_path_x64(),
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-Command",
]


def _ps(script: str, *, timeout: float = 30.0) -> Tuple[str, int]:
    """
    Run PowerShell hidden. Return (stdout+stderr, rc). Never raises.
    Adds Import-Module Defender and ErrorAction Stop.
    """
    if platform.system() != "Windows":
        return "Not Windows", -1
    cmd = (
        "$ErrorActionPreference='Stop';"
        "Import-Module Defender -ErrorAction SilentlyContinue | Out-Null;"
        + script
    )
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

# ------------------------------- services -----------------------------------


def _svc_start(name: str) -> tuple[bool, Optional[str]]:
    if ensure_admin():
        _ps(
            "try { "
            f"Set-Service -Name {name} -StartupType Automatic -EA SilentlyContinue; "
            f"if ((Get-Service -Name {name}).Status -ne 'Running') {{ Start-Service -Name {name} -EA SilentlyContinue }} "
            "} catch {}"
        )
    out, rc = _ps(f"(Get-Service -Name {name}).Status")
    if rc == 0 and "Running" in out:
        return True, None
    return False, f"{name} not running"


def _defender_services_ok() -> tuple[bool, Optional[str]]:
    """Check and start core Defender services.
    Returns (ok, err_text)."""
    for svc in ("WinDefend", "SecurityHealthService"):
        ok, err = _svc_start(svc)
        if not ok:
            return False, err
    return True, None

# ------------------------------- queries ------------------------------------


def is_defender_supported() -> bool:
    if platform.system() != "Windows":
        return False
    out, rc = _ps("(Get-Command Get-MpComputerStatus -EA SilentlyContinue) -ne $null")
    return rc == 0 and "True" in out


def _is_defender_enabled_raw() -> Tuple[Optional[bool], Optional[str]]:
    if platform.system() != "Windows":
        return None, "Not Windows"
    out, rc = _ps("(Get-MpComputerStatus).RealTimeProtectionEnabled")
    if rc != 0:
        return None, out or "Get-MpComputerStatus failed"
    v = out.strip().splitlines()[-1].strip().lower()
    if v == "true":
        return True, None
    if v == "false":
        return False, None
    return None, f"Unexpected output: {v}"


def is_defender_enabled() -> Optional[bool]:
    v, _ = _is_defender_enabled_raw()
    return v


def _tamper_on_raw() -> Tuple[Optional[bool], Optional[str]]:
    out, rc = _ps("(Get-MpPreference).TamperProtection")
    if rc != 0:
        return None, out or "Get-MpPreference failed"
    val = out.strip().splitlines()[-1].strip().lower()
    if val in {"on", "off"}:
        return val == "on", None
    return None, f"Unexpected output: {val}"


def _tamper_on() -> Optional[bool]:
    v, _ = _tamper_on_raw()
    return v


def _third_party_av_present() -> bool:
    return bool(third_party_av_names())


def third_party_av_names() -> tuple[str, ...]:
    """Return registered non-Defender antivirus products."""

    ps = (
        "($p=Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -EA SilentlyContinue) | "
        "Where-Object { $_.displayName -ne $null -and $_.displayName -notlike '*Defender*' } | "
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
    return tuple(dict.fromkeys(names))


def _policy_lock_present() -> bool:
    ps = (
        "try { "
        "$k='HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows Defender'; "
        "Test-Path $k -PathType Container "
        "} catch { $false }"
    )
    out, rc = _ps(ps)
    return rc == 0 and "True" in out


@dataclass
class DefenderStatus:
    realtime: Optional[bool]
    tamper_on: Optional[bool]
    cmdlets_available: bool
    services_ok: bool
    third_party_av_present: bool
    policy_lock: bool
    services_error: Optional[str] = None
    error: Optional[str] = None
    third_party_names: tuple[str, ...] = ()


def get_defender_status() -> DefenderStatus:
    if platform.system() != "Windows":
        return DefenderStatus(
            None,
            None,
            False,
            False,
            False,
            False,
            None,
            "Not Windows",
            (),
        )
    rt, err_rt = _is_defender_enabled_raw()
    tp, err_tp = _tamper_on_raw()
    svc_ok, svc_err = _defender_services_ok()
    err = err_rt or err_tp or svc_err
    return DefenderStatus(
        realtime=rt,
        tamper_on=tp,
        cmdlets_available=is_defender_supported(),
        services_ok=svc_ok,
        third_party_av_present=_third_party_av_present(),
        policy_lock=_policy_lock_present(),
        services_error=svc_err,
        error=err,
        third_party_names=third_party_av_names(),
    )

# ------------------------------- toggling -----------------------------------


def _registry_toggle_rt(disable: bool) -> Tuple[bool, str]:
    """
    Fallback when Set-MpPreference succeeds but state does not change.
    Tamper Protection may still override. Uses reg.exe then restarts service.
    """
    dword = "1" if disable else "0"
    key = r"HKLM\SOFTWARE\Microsoft\Windows Defender\Real-Time Protection"
    out_add, rc_add = _run_ex(["reg", "add", key, "/v", "DisableRealtimeMonitoring", "/t", "REG_DWORD", "/d", dword, "/f"])
    if rc_add != 0:
        return False, out_add or "reg add failed"
    _run_ex(["sc", "stop", "WinDefend"])
    time.sleep(0.8)
    _run_ex(["sc", "start", "WinDefend"])
    return True, "registry toggle applied"


def _run_ex(cmd: list[str], timeout: float = 25.0) -> Tuple[str, int]:
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


def set_defender_enabled(enabled: bool) -> tuple[bool, Optional[str]]:
    """
    Enable/disable Defender realtime with verification and diagnostics.
    Returns (ok, error_text).
    """
    if platform.system() != "Windows":
        return True, None

    if not ensure_admin():
        return False, "Administrator privileges required."

    if not is_defender_supported():
        return False, "Defender PowerShell cmdlets unavailable."
    svc_ok, svc_err = _defender_services_ok()
    if not svc_ok:
        return False, f"Defender services could not be started ({svc_err})."
    if _third_party_av_present():
        return False, "Another antivirus is registered. Disable or remove it first."

    want = enabled
    cur = is_defender_enabled()
    if cur is not None and cur == want:
        return True, None

    flag = "$false" if enabled else "$true"
    out, rc = _ps(f"Set-MpPreference -DisableRealtimeMonitoring {flag} -Force")
    if rc != 0 and out:
        return False, out

    for i in range(7):
        time.sleep(0.5 + i * 0.25)
        st = is_defender_enabled()
        if st is not None and st == want:
            return True, None

    if _tamper_on():
        return False, "Tamper Protection is ON. Turn it OFF in Windows Security → Virus & threat protection → Tamper Protection."

    if _policy_lock_present():
        return False, "Policy lock detected. Device is managed by policy. Clear policy or change MDM/GPO settings."

    ok_reg, why = _registry_toggle_rt(disable=(not enabled))
    if ok_reg:
        time.sleep(1.2)
        st = is_defender_enabled()
        if st is not None and st == want:
            return True, None
    elif "AccessDenied" in why:
        return False, why

    err = out or "Failed to run Set-MpPreference"
    if rc == 0:
        err = f"Defender state unchanged. {why if ok_reg else err}"
    return False, err
