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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List

from src.app import error_handler as eh


# ----------------------------- Platform helpers ----------------------------

def _is_windows() -> bool:
    return platform.system() == "Windows"


# Creation flags to suppress any console windows on Windows
CREATE_NO_WINDOW = 0x08000000 if _is_windows() else 0


# ------------------------------ Admin check --------------------------------


def is_admin() -> bool:
    if _is_windows():
        try:  # pragma: no cover - Windows specific
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


def ensure_admin() -> bool:
    """Compatibility shim used by other modules/tests."""
    return is_admin()


def launch_security_center(*, hide_console: bool = False) -> bool:
    """Launch the standalone Security Center script."""
    script_name = "security_center_hidden.py" if hide_console else "security_center.py"
    script = Path(__file__).resolve().parents[2] / "scripts" / script_name
    if not script.exists():
        return False
    py = Path(sys.executable)
    if _is_windows():
        if is_admin():
            ok, _ = run_command_background(
                [str(py), str(script)], creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            return ok
        try:
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(py), f'"{script}"', None, 1
            )
            return r > 32
        except Exception as e:  # pragma: no cover - elevation failure
            eh.handle_exception(type(e), e, e.__traceback__)
            return False
    if is_admin():
        ok, _ = run_command_background([str(py), str(script)])
        return ok
    ok, _ = run_command_background(["sudo", str(py), str(script)])
    return ok


@dataclass
class RunResult:
    code: int
    out: str
    err: str


_lock = threading.RLock()


def _run(cmd: List[str], timeout: int = 30) -> RunResult:
    """Run a command with no visible window. Returns stdout, stderr, code."""
    try:
        with _lock:
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
        return RunResult(proc.returncode, out.strip(), err.strip())
    except Exception as e:  # pragma: no cover - subprocess failure
        eh.handle_exception(type(e), e, e.__traceback__)
        return RunResult(-1, "", str(e))


def _run_ps(ps_script: str, timeout: int = 30) -> RunResult:
    """Run a PowerShell one-liner invisibly with hardened flags."""
    if not _is_windows():
        return RunResult(1, "", "Windows-only")
    cmd = [
        "powershell",
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
    """Run a command in background, logging any exception via error handler."""
    try:
        p = subprocess.Popen(cmd, **popen_kwargs)
        return True, p
    except Exception as e:  # pragma: no cover - popen failure
        eh.handle_exception(type(e), e, e.__traceback__)
        return False, None


def _run_ex(cmd: List[str], timeout: int = 30) -> Tuple[str, int]:
    rr = _run(cmd, timeout=timeout)
    return rr.out, rr.code


def _run_rc(cmd: List[str], timeout: int = 30) -> int:
    rr = _run(cmd, timeout=timeout)
    return rr.code


def _ps(script: str, timeout: int = 30) -> Tuple[str, int]:
    rr = _run_ps(script, timeout=timeout)
    return rr.out, rr.code


# ------------------------------- Firewall ----------------------------------


def is_firewall_enabled() -> Optional[bool]:
    """
    True if all profiles enabled, False if any disabled, None if unknown.
    Uses 'netsh advfirewall show allprofiles' to avoid module dependencies.
    """
    if platform.system() != "Windows":
        return None

    out, code = _run_ex(["netsh", "advfirewall", "show", "allprofiles"])
    if code != 0:
        return None

    states = re.findall(r"State\s+(\w+)", out, flags=re.IGNORECASE)
    if not states:
        return None
    on_all = all(s.lower() in ("on", "enabled", "1") for s in states)
    return True if on_all else False


def set_firewall_enabled(enabled: bool) -> bool:
    """Enable or disable firewall for all profiles via netsh. Admin required."""
    if platform.system() != "Windows":
        return False
    state = "on" if enabled else "off"
    rc = _run_rc(["netsh", "advfirewall", "set", "allprofiles", "state", state])
    if rc != 0:
        return False
    chk = is_firewall_enabled()
    if chk is None:
        return True
    return (chk is True) if enabled else (chk is False)


# --------------------------- Defender (WinDefend) ---------------------------


def _service_query(name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (state, start_type) for a service via sc.exe query.
    state: RUNNING | STOPPED | START_PENDING | STOP_PENDING ...
    start_type: AUTO_START | DEMAND_START | DISABLED | ...
    """
    if platform.system() != "Windows":
        return None, None

    q = _run(["sc", "query", name])
    if q.code != 0:
        return None, None

    m_state = re.search(r"STATE\s*:\s*\d+\s+([A-Z_]+)", q.out)
    state = m_state.group(1) if m_state else None

    q2 = _run(["sc", "qc", name])
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
    """Set WinDefend to AUTO_START using sc.exe."""
    if platform.system() != "Windows":
        return False
    res = _run(["sc", "config", "WinDefend", "start=", "auto"])
    if res.code != 0:
        return False
    _, start_type = _service_query("WinDefend")
    return start_type == "AUTO_START"


def start_defender_service() -> bool:
    """Start WinDefend service if not running."""
    if platform.system() != "Windows" or not is_admin():
        return False
    state = defender_service_status()
    if state == "RUNNING":
        return True
    res = _run(["sc", "start", "WinDefend"])
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
    if platform.system() != "Windows" or not is_admin():
        return False
    res = _run(["sc", "stop", "WinDefend"])
    if res.code != 0:
        state = defender_service_status()
        return state == "STOPPED"
    state = defender_service_status()
    return state == "STOPPED"


def _defender_cmdlets_available() -> bool:
    """Placeholder for tests; assumes cmdlets available on Windows."""
    return _is_windows()


def _defender_services_ok() -> bool:
    """Placeholder for tests; assumes services are running."""
    return True


def _third_party_av_present() -> bool:
    """Placeholder for tests; assume no third-party AV."""
    return False


def _defender_tamper_on() -> bool:
    """Placeholder for tests; assume tamper protection off."""
    return False


def _policy_lock_present() -> bool:
    """Placeholder for tests; assume no policy lock."""
    return False


def _managed_by_org() -> bool:
    """Placeholder for tests; assume device unmanaged."""
    return False


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
    if not _is_windows():
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
    out, code = _ps(ps)
    realtime = antispy = anti = tamper = None
    if code == 0 and out:
        try:
            data = json.loads(out)
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


def set_defender_realtime(enabled: bool) -> bool:
    """Toggle Defender real-time protection using Set-MpPreference."""
    if platform.system() != "Windows":
        return False
    disable_flag = "True" if not enabled else "False"
    ps = f"$ErrorActionPreference='Stop'; Set-MpPreference -DisableRealtimeMonitoring {disable_flag}"
    out, code = _ps(ps)
    return code == 0


# -------------------------- Composite high-level API ------------------------


def is_defender_realtime_on() -> Optional[bool]:
    return get_defender_status().realtime_enabled


def set_defender_enabled(enabled: bool) -> Tuple[bool, Optional[str]]:
    """
    Best-effort enable/disable Defender functionality used by UI:
    - Ensure service AUTO_START and running when enabling.
    - For 'disable', stop service; if blocked, fall back to disabling realtime.
    """
    if platform.system() != "Windows":
        return False, "Unsupported"
    if not _defender_cmdlets_available():
        return False, "Cmdlets unavailable"

    if enabled:
        if _defender_services_ok():
            ok = set_defender_realtime(True)
        else:
            ok = ensure_defender_autostart()
            ok = start_defender_service() and ok
            ok = set_defender_realtime(True) and ok
        return (ok, None if ok else "Failed")
    else:
        if stop_defender_service():
            return True, None
        ok = set_defender_realtime(False)
        return (ok, None if ok else "Failed")


def is_defender_enabled() -> Optional[bool]:
    """Return Defender realtime status."""
    if not is_defender_supported():
        return None
    out, code = _ps("(Get-MpComputerStatus).RealTimeProtectionEnabled")
    if code != 0:
        return None
    val = out.strip().splitlines()[-1].strip().lower()
    if val == "true":
        return True
    if val == "false":
        return False
    return None


def is_defender_supported() -> bool:
    """Simple check for platform support."""
    return _is_windows()


def read_current_states() -> Tuple[Optional[bool], Optional[bool]]:
    fw = is_firewall_enabled()
    df = is_defender_enabled() if _is_windows() else None
    return fw, df


__all__ = [
    "DefenderStatus",
    "ensure_admin",
    "get_defender_status",
    "is_admin",
    "is_defender_enabled",
    "is_defender_realtime_on",
    "is_defender_supported",
    "is_firewall_enabled",
    "launch_security_center",
    "read_current_states",
    "run_command_background",
    "set_defender_enabled",
    "set_defender_realtime",
    "set_firewall_enabled",
]


# ------------------------------ Module self-test ----------------------------

if __name__ == "main":  # pragma: no cover
    print(f"Admin: {is_admin()}")
    print(f"Firewall enabled: {is_firewall_enabled()}")
    print(f"Defender status: {get_defender_status()}")
