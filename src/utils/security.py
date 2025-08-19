# -*- coding: utf-8 -*-
"""
Security utilities for Windows Firewall and Microsoft Defender.
No visible shells. Robust service control. Thread-safe helpers.

Tested on Windows 10/11. Requires admin.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List

from src.app import error_handler as eh


# ----------------------------- Platform guard ------------------------------

_IS_WINDOWS = platform.system() == "Windows"

# Creation flags to suppress any console windows on Windows
CREATE_NO_WINDOW = 0x08000000 if _IS_WINDOWS else 0

# Path to sc.exe to avoid PowerShell alias collision with Set-Content
_SC_EXE = r"C:\\Windows\\System32\\sc.exe" if _IS_WINDOWS else None
_NETSH_EXE = r"C:\\Windows\\System32\\netsh.exe" if _IS_WINDOWS else None
_POWERSHELL_EXE = (
    r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    if _IS_WINDOWS
    else None
)


# ------------------------------ Admin check --------------------------------

def is_admin() -> bool:
    if not _IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin() -> bool:
    return is_admin()


# ------------------------------ Run helpers --------------------------------

@dataclass
class RunResult:
    code: int
    out: str
    err: str

_lock = threading.RLock()

def _run(cmd: List[str], timeout: int = 30) -> RunResult:
    """Run a command with no visible window. Returns stdout, stderr, code."""
    with _lock:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                text=True,
                encoding="utf-8",
            )
            out, err = proc.communicate(timeout=timeout)
        except Exception as e:  # pragma: no cover - subprocess failure
            eh.handle_exception(type(e), e, e.__traceback__)
            return RunResult(1, "", str(e))
    return RunResult(proc.returncode, out.strip(), err.strip())


def _run_ps(ps_script: str, timeout: int = 30) -> RunResult:
    """Run a PowerShell one-liner invisibly with hardened flags."""
    if not _IS_WINDOWS:
        return RunResult(1, "", "Windows-only")
    cmd = [
        _POWERSHELL_EXE,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        ps_script,
    ]
    return _run(cmd, timeout=timeout)


def run_command_background(
    cmd: List[str], **popen_kwargs
) -> Tuple[bool, Optional[subprocess.Popen]]:
    """Run *cmd* in background returning (ok, Popen) and suppressing errors."""
    try:
        p = subprocess.Popen(cmd, **popen_kwargs)
        return True, p
    except Exception as e:  # pragma: no cover - popen failure
        eh.handle_exception(type(e), e, e.__traceback__)
        return False, None


def launch_security_center(*, hide_console: bool = False) -> bool:
    script_name = "security_center_hidden.py" if hide_console else "security_center.py"
    script = Path(__file__).resolve().parents[2] / "scripts" / script_name
    if not script.exists():
        return False
    py = Path(sys.executable)
    if _IS_WINDOWS:
        if is_admin():
            ok, _ = run_command_background(
                [str(py), str(script)], creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            return ok
        try:  # pragma: no cover - Windows specific elevation
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(py), f'"{script}"', None, 1
            )
            return r > 32
        except Exception as e:
            eh.handle_exception(type(e), e, e.__traceback__)
            return False
    # Unix: best effort using sudo
    if is_admin():
        ok, _ = run_command_background([str(py), str(script)])
        return ok
    ok, _ = run_command_background(["sudo", str(py), str(script)])
    return ok


# ------------------------------- Firewall ----------------------------------

def is_firewall_enabled() -> Optional[bool]:
    """
    True if all profiles enabled, False if any disabled, None if unknown.
    Uses 'netsh advfirewall show allprofiles' to avoid module dependencies.
    """
    if not _IS_WINDOWS:
        return None
    if not _NETSH_EXE or not os.path.exists(_NETSH_EXE):
        return None

    res = _run([_NETSH_EXE, "advfirewall", "show", "allprofiles"])
    if res.code != 0:
        return None

    states = re.findall(r"State\s+(\w+)", res.out, flags=re.IGNORECASE)
    if not states:
        return None
    on_all = all(s.lower() in ("on", "enabled", "1") for s in states)
    return True if on_all else False


def set_firewall_enabled(enabled: bool) -> bool:
    """Enable or disable firewall for all profiles via netsh. Admin required."""
    if not _IS_WINDOWS or not is_admin():
        return False
    if not _NETSH_EXE or not os.path.exists(_NETSH_EXE):
        return False
    state = "on" if enabled else "off"
    res = _run([_NETSH_EXE, "advfirewall", "set", "allprofiles", "state", state])
    if res.code != 0:
        return False
    chk = is_firewall_enabled()
    return (chk is True) if enabled else (chk is False)


# --------------------------- Defender (WinDefend) ---------------------------

def _service_query(name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (state, start_type) for a service via sc.exe query.
    state: RUNNING | STOPPED | START_PENDING | STOP_PENDING ...
    start_type: AUTO_START | DEMAND_START | DISABLED | ...
    """
    if not _IS_WINDOWS or not _SC_EXE or not os.path.exists(_SC_EXE):
        return None, None

    q = _run([_SC_EXE, "query", name])
    if q.code != 0:
        return None, None

    m_state = re.search(r"STATE\s*:\s*\d+\s+([A-Z_]+)", q.out)
    state = m_state.group(1) if m_state else None

    q2 = _run([_SC_EXE, "qc", name])
    start_type = None
    if q2.code == 0:
        m_start = re.search(r"START_TYPE\s*:\s*\d+\s+([A-Z_]+)", q2.out)
        start_type = m_start.group(1) if m_start else None

    return state, start_type


def defender_service_status() -> Optional[str]:
    """Return 'RUNNING' or 'STOPPED' for WinDefend, else None."""
    state, _ = _service_query("WinDefend")
    return state


def ensure_defender_autostart() -> bool:
    """Set WinDefend to AUTO_START using sc.exe, avoiding PowerShell alias issues."""
    if not _IS_WINDOWS or not is_admin():
        return False
    res = _run([_SC_EXE, "config", "WinDefend", "start=", "auto"])
    if res.code != 0:
        return False
    _, start_type = _service_query("WinDefend")
    return start_type == "AUTO_START"


def start_defender_service() -> bool:
    """Start WinDefend service if not running."""
    if not _IS_WINDOWS or not is_admin():
        return False
    state = defender_service_status()
    if state == "RUNNING":
        return True
    res = _run([_SC_EXE, "start", "WinDefend"])
    if res.code != 0:
        state = defender_service_status()
        return state == "RUNNING"
    state = defender_service_status()
    return state == "RUNNING"


def stop_defender_service() -> bool:
    """
    Stop WinDefend. May be blocked by Tamper Protection or policy.
    Returns False if blocked.
    """
    if not _IS_WINDOWS or not is_admin():
        return False
    res = _run([_SC_EXE, "stop", "WinDefend"])
    if res.code != 0:
        state = defender_service_status()
        return state == "STOPPED"
    state = defender_service_status()
    return state == "STOPPED"


# ---------------------- Defender real-time protection -----------------------

@dataclass
class DefenderStatus:
    service_state: Optional[str]
    realtime_enabled: Optional[bool]
    antispyware_enabled: Optional[bool]
    antivirus_enabled: Optional[bool]
    tamper_protection: Optional[bool]

def get_defender_status() -> DefenderStatus:
    """
    Query Defender using Get-MpComputerStatus. Returns summarized booleans.
    """
    if not _IS_WINDOWS:
        return DefenderStatus(None, None, None, None, None)

    ps = r"""
    $ErrorActionPreference='Stop';
    if (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue) {
        $s = Get-MpComputerStatus
        $obj = [ordered]@{
            Realtime=$s.RealTimeProtectionEnabled
            AS=$s.AntispywareEnabled
            AV=$s.AntivirusEnabled
            Tamper=$s.IsTamperProtected
        }
        $obj | ConvertTo-Json -Compress
    } else {
        '{}' | ConvertTo-Json
    }
    """
    rr = _run_ps(ps)
    realtime = antispy = anti = tamper = None
    if rr.code == 0 and rr.out:
        try:
            data = json.loads(rr.out)
            realtime = bool(data.get("Realtime")) if "Realtime" in data else None
            antispy = bool(data.get("AS")) if "AS" in data else None
            anti = bool(data.get("AV")) if "AV" in data else None
            tamper = bool(data.get("Tamper")) if "Tamper" in data else None
        except Exception:
            pass
    return DefenderStatus(
        service_state=defender_service_status(),
        realtime_enabled=realtime,
        antispyware_enabled=antispy,
        antivirus_enabled=anti,
        tamper_protection=tamper,
    )


def is_defender_enabled() -> Optional[bool]:
    return get_defender_status().realtime_enabled


def is_defender_supported() -> bool:
    return _IS_WINDOWS


def set_defender_realtime(enabled: bool) -> bool:
    """
    Toggle Defender real-time protection using Set-MpPreference.
    This does not disable the product, only RealTimeProtection.
    """
    if not _IS_WINDOWS or not is_admin():
        return False

    disable_flag = "True" if not enabled else "False"
    ps = f"$ErrorActionPreference='Stop'; Set-MpPreference -DisableRealtimeMonitoring {disable_flag}"
    rr = _run_ps(ps)
    if rr.code != 0:
        return False

    st = get_defender_status()
    return (st.realtime_enabled is True) if enabled else (st.realtime_enabled is False)


def set_defender_enabled(enabled: bool) -> bool:
    """
    Best-effort enable/disable Defender functionality used by UI:
    - Ensure service AUTO_START and running when enabling.
    - For 'disable', stop service; if blocked, fall back to disabling realtime.
    """
    if not _IS_WINDOWS or not is_admin():
        return False

    if enabled:
        ok = ensure_defender_autostart()
        ok = start_defender_service() and ok
        rt = set_defender_realtime(True)
        return ok and rt
    else:
        if stop_defender_service():
            return True
        return set_defender_realtime(False)


def is_defender_realtime_on() -> Optional[bool]:
    return get_defender_status().realtime_enabled


# ------------------------------ Aggregate state ----------------------------

def read_current_states() -> Tuple[Optional[bool], Optional[bool]]:
    fw = is_firewall_enabled()
    df = is_defender_enabled()
    return fw, df


__all__ = [
    "RunResult",
    "is_admin",
    "ensure_admin",
    "run_command_background",
    "launch_security_center",
    "is_firewall_enabled",
    "set_firewall_enabled",
    "defender_service_status",
    "ensure_defender_autostart",
    "start_defender_service",
    "stop_defender_service",
    "get_defender_status",
    "set_defender_realtime",
    "set_defender_enabled",
    "is_defender_realtime_on",
    "is_defender_enabled",
    "is_defender_supported",
    "read_current_states",
]


if __name__ == "__main__":
    print(f"Admin: {is_admin()}")
    print(f"Firewall enabled: {is_firewall_enabled()}")
    print(f"Set firewall on: {set_firewall_enabled(True)}")
    print(f"Defender status: {get_defender_status()}")
    print(f"Enable Defender: {set_defender_enabled(True)}")
    print(f"Disable realtime: {set_defender_realtime(False)}")
