# -*- coding: utf-8 -*-
"""
Security utilities: firewall + Windows Defender with deep diagnostics.

Highlights
- Uses 64-bit PowerShell (Sysnative) to avoid WOW64 issues.
- Starts Defender services if stopped. Verifies after every change.
- Detects Tamper Protection, policy locks, EDR/MDM, and 3rd-party AV.
- Clear, actionable error text. Idempotent operations.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.app import error_handler as eh


# ------------------------------- helpers ------------------------------------

def _which(exe: str) -> Optional[str]:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for p in paths:
        fp = Path(p) / exe
        if fp.exists():
            return str(fp)
    return None


def _run_ex(
    cmd: list[str] | str, *, capture: bool = True, timeout: float | None = 30.0
) -> Tuple[str, int]:
    try:
        shell = isinstance(cmd, str)
        cp = subprocess.run(
            cmd, capture_output=capture, text=True, timeout=timeout, shell=shell
        )
        out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
        return out.strip(), int(cp.returncode)
    except Exception as e:  # pragma: no cover - subprocess failure
        eh.handle_exception(type(e), e, e.__traceback__)
        return f"{type(e).__name__}: {e}", -1


def _run_rc(cmd: list[str] | str, *, timeout: float | None = 30.0) -> Optional[int]:
    out, code = _run_ex(cmd, timeout=timeout)
    return code if code >= 0 else None


def run_command_background(
    cmd: list[str], **popen_kwargs
) -> Tuple[bool, Optional[subprocess.Popen]]:
    try:
        p = subprocess.Popen(cmd, **popen_kwargs)
        return True, p
    except Exception as e:  # pragma: no cover - popen failure
        eh.handle_exception(type(e), e, e.__traceback__)
        return False, None


# ------------------------------- elevation ----------------------------------


def is_admin() -> bool:
    if platform.system() != "Windows":
        return os.geteuid() == 0  # type: ignore[attr-defined]
    try:  # pragma: no cover - Windows specific
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return False


def ensure_admin() -> bool:
    return is_admin()


def launch_security_center(*, hide_console: bool = False) -> bool:
    script_name = "security_center_hidden.py" if hide_console else "security_center.py"
    script = Path(__file__).resolve().parents[2] / "scripts" / script_name
    if not script.exists():
        return False
    py = Path(sys.executable)
    if platform.system() == "Windows":
        if is_admin():
            ok, _ = run_command_background(
                [str(py), str(script)], creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            return ok
        try:  # pragma: no cover - Windows specific
            import ctypes

            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(py), f'"{script}"', None, 1
            )
            return r > 32
        except Exception as e:
            eh.handle_exception(type(e), e, e.__traceback__)
            return False
    # Unix
    if is_admin():
        ok, _ = run_command_background([str(py), str(script)])
        return ok
    ok, _ = run_command_background(["sudo", str(py), str(script)])
    return ok


# ------------------------------- firewall -----------------------------------


def _unix_firewall_tool() -> Optional[str]:
    if _which("ufw"):
        return "ufw"
    if _which("firewall-cmd"):
        return "firewall-cmd"
    if platform.system() == "Darwin" and _which("pfctl"):
        return "pfctl"
    return None


def is_firewall_enabled() -> Optional[bool]:
    try:
        if platform.system() == "Windows":
            out, code = _run_ex(["netsh", "advfirewall", "show", "allprofiles"])
            if code != 0:
                return None
            return "State ON" in out or "State                  ON" in out
        tool = _unix_firewall_tool()
        if tool == "ufw":
            out, code = _run_ex(["ufw", "status"])
            return "Status: active" in out if code == 0 else None
        if tool == "firewall-cmd":
            _, code = _run_ex(["systemctl", "is-active", "--quiet", "firewalld"])
            return code == 0
        if tool == "pfctl":
            out, code = _run_ex(["pfctl", "-s", "info"])
            return ("Status: Enabled" in out) if code == 0 else None
        return None
    except Exception as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        return None


def set_firewall_enabled(enabled: bool) -> bool:
    if platform.system() == "Windows":
        state = "on" if enabled else "off"
        return _run_rc(["netsh", "advfirewall", "set", "allprofiles", "state", state]) == 0
    tool = _unix_firewall_tool()
    if tool == "ufw":
        cmd = ["ufw", "enable"] if enabled else ["ufw", "disable"]
    elif tool == "firewall-cmd":
        cmd = ["systemctl", "start" if enabled else "stop", "firewalld"]
    elif tool == "pfctl":
        cmd = ["pfctl", "-e"] if enabled else ["pfctl", "-d"]
    else:
        return False
    return _run_rc(cmd) == 0


# ---------------------------- Windows Defender ------------------------------


def _ps_path_x64() -> str:
    root = os.environ.get("SystemRoot", r"C:\\Windows")
    # Sysnative breaks WOW64 redirection for 32-bit hosts on x64
    if platform.machine().endswith("64") and "PROGRAMFILES(X86)" in os.environ:
        p = (
            Path(root)
            / "Sysnative"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if p.exists():
            return str(p)
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


_PS_BASE = [
    _ps_path_x64(),
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
]


def _ps(script: str, *, timeout: float = 30.0) -> Tuple[str, int]:
    cmd = (
        "$ErrorActionPreference='Stop';"
        "Import-Module Defender -ErrorAction SilentlyContinue | Out-Null;"
        + script
    )
    return _run_ex(_PS_BASE + [cmd], timeout=timeout)


@dataclass
class DefenderStatus:
    realtime: Optional[bool]
    tamper_on: Optional[bool]
    cmdlets_available: bool
    services_ok: bool
    third_party_av_present: bool
    policy_lock: bool
    managed_by_org: bool
    error: Optional[str] = None


def _svc_start(name: str) -> bool:
    # Try PowerShell first; fall back to sc.exe
    _ps(
        f"Set-Service -Name {name} -StartupType Automatic; "
        f"If ((Get-Service -Name {name}).Status -ne 'Running') {{ Start-Service -Name {name} -ErrorAction SilentlyContinue }}"
    )
    out, code = _ps(f"(Get-Service -Name {name}).Status")
    return code == 0 and "Running" in out


def _defender_services_ok() -> bool:
    ok1 = _svc_start("WinDefend")
    ok2 = _svc_start("SecurityHealthService")
    return ok1 and ok2


def _defender_cmdlets_available() -> bool:
    out, code = _ps("(Get-Command Get-MpComputerStatus -EA SilentlyContinue) -ne $null")
    return code == 0 and "True" in out


def _defender_tamper_on() -> Optional[bool]:
    out, code = _ps("(Get-MpPreference).TamperProtection")
    if code != 0:
        return None
    v = out.strip().splitlines()[-1].strip().lower()
    return True if v == "on" else False if v == "off" else None


def _third_party_av_present() -> bool:
    ps = (
        "($p=Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction SilentlyContinue) | "
        "Where-Object { $_.displayName -notlike '*Defender*' -and $_.displayName -ne $null } | "
        "Measure-Object | % Count"
    )
    out, code = _ps(ps)
    try:
        n = int(out.strip().splitlines()[-1])
    except Exception as e:
        eh.handle_exception(type(e), e, e.__traceback__)
        n = 0 if code != 0 else 0
    return n > 0


def _policy_lock_present() -> bool:
    ps = (
        "try { "
        "$p=(Get-ItemProperty 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows Defender\\Real-Time Protection' "
        "-EA Stop); "
        "($p.DisableRealtimeMonitoring -ne $null) "
        "} catch { $false }"
    )
    out, code = _ps(ps)
    return code == 0 and "True" in out


def _managed_by_org() -> bool:
    ps = (
        "Test-Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows Defender' "
        "-PathType Container"
    )
    out, code = _ps(ps)
    return code == 0 and "True" in out


def is_defender_supported() -> bool:
    return platform.system() == "Windows" and _defender_cmdlets_available()


def is_defender_enabled() -> Optional[bool]:
    if platform.system() != "Windows":
        return None
    out, code = _ps("(Get-MpComputerStatus).RealTimeProtectionEnabled")
    if code != 0:
        return None
    val = out.strip().splitlines()[-1].strip().lower()
    return True if val == "true" else False if val == "false" else None


def get_defender_status() -> DefenderStatus:
    if platform.system() != "Windows":
        return DefenderStatus(
            None, None, False, False, False, False, False, "Not Windows"
        )
    return DefenderStatus(
        realtime=is_defender_enabled(),
        tamper_on=_defender_tamper_on(),
        cmdlets_available=_defender_cmdlets_available(),
        services_ok=_defender_services_ok(),
        third_party_av_present=_third_party_av_present(),
        policy_lock=_policy_lock_present(),
        managed_by_org=_managed_by_org(),
        error=None,
    )


def _registry_toggle_rt(disable: bool) -> Tuple[bool, str]:
    dword = "1" if disable else "0"
    key = r"HKLM\SOFTWARE\Microsoft\Windows Defender\Real-Time Protection"
    out, code = _run_ex(
        [
            "reg",
            "add",
            key,
            "/v",
            "DisableRealtimeMonitoring",
            "/t",
            "REG_DWORD",
            "/d",
            dword,
            "/f",
        ]
    )
    if code != 0:
        return False, out or "reg add failed"
    _run_ex(["sc", "stop", "WinDefend"])
    time.sleep(0.8)
    _run_ex(["sc", "start", "WinDefend"])
    return True, "registry path used"


def set_defender_enabled(enabled: bool) -> Tuple[bool, Optional[str]]:
    """
    Enable/disable Defender realtime with deep verification.
    Returns (ok, error_text).
    """
    if platform.system() != "Windows":
        return True, None

    if not _defender_cmdlets_available():
        return False, "Defender PowerShell cmdlets unavailable."
    if not _defender_services_ok():
        return False, "Defender services could not be started."
    if _third_party_av_present():
        return False, "Another antivirus is registered. Uninstall/disable it or set Defender as primary."

    want = enabled
    cur = is_defender_enabled()
    if cur is not None and cur == want:
        return True, None

    flip = "$false" if enabled else "$true"
    out, code = _ps(f"Set-MpPreference -DisableRealtimeMonitoring {flip} -Force")
    for i in range(6):
        time.sleep(0.6 + i * 0.2)
        state = is_defender_enabled()
        if state is not None and state == want:
            return True, None

    if _defender_tamper_on():
        return (
            False,
            "Tamper Protection is ON. Turn it OFF in Windows Security → Virus & threat protection → Tamper Protection.",
        )

    if _policy_lock_present() or _managed_by_org():
        return (
            False,
            "Policy lock detected. This device is managed by policy. Clear Defender policy keys or contact admin/MDM.",
        )

    ok_reg, why = _registry_toggle_rt(disable=(not enabled))
    if ok_reg:
        time.sleep(1.5)
        state = is_defender_enabled()
        if state is not None and state == want:
            return True, None

    err = out or "Failed to run Set-MpPreference"
    if code == 0:
        err = f"Defender state unchanged. {why if ok_reg else err}"
    return False, err


# --------------------------- aggregate state --------------------------------


def read_current_states() -> Tuple[Optional[bool], Optional[bool]]:
    fw = is_firewall_enabled()
    df = is_defender_enabled() if platform.system() == "Windows" else None
    return fw, df


__all__ = [
    "DefenderStatus",
    "ensure_admin",
    "get_defender_status",
    "is_admin",
    "is_defender_enabled",
    "is_defender_supported",
    "is_firewall_enabled",
    "launch_security_center",
    "read_current_states",
    "run_command_background",
    "set_defender_enabled",
    "set_firewall_enabled",
]

