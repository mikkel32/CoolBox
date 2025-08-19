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
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
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
    # SecurityCenter2\FirewallProduct reports registered non-MS firewalls
    ps = (
        "($p=Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct -EA SilentlyContinue) | "
        "Where-Object { $_.displayName -ne $null -and $_.displayName -notlike '*Windows*' } | "
        "Measure-Object | % Count"
    )
    out, rc = _ps(ps)
    try:
        n = int(out.strip().splitlines()[-1])
    except Exception:
        n = 0 if rc != 0 else 0
    return n > 0


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


def is_firewall_supported() -> bool:
    return platform.system() == "Windows"


def is_firewall_enabled() -> Optional[bool]:
    if platform.system() != "Windows":
        return None
    d, p, u, _ = _get_profile_states()
    if any(v is None for v in (d, p, u)):
        return None
    return bool(d) and bool(p) and bool(u)


def get_firewall_status() -> FirewallStatus:
    if platform.system() != "Windows":
        return FirewallStatus(None, None, None, False, False, False, False, None, "Not Windows")
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
    if platform.system() != "Windows":
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
