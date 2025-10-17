"""Windows Defender orchestration built on top of the shared security core."""
from __future__ import annotations

import json
import os
import re
from typing import Optional, Tuple

from . import defender as defender_utils
from . import platform as platform_state
from .core import (
    ActionOutcome,
    DefenderStatus,
    RunResult,
    OutcomeBuilder,
    TogglePipeline,
    build_toggle_plan,
    dedupe,
    drive_service_state,
    guarded_call,
    run_command,
    run_powershell,
)
from .admin import is_admin

RUN_COMMAND = run_command
RUN_POWERSHELL = run_powershell


def _service_query(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(state, start_type)`` for a service via ``sc.exe query``."""

    sc_exe = platform_state.SC_EXE
    if not platform_state.IS_WINDOWS or not sc_exe or not os.path.exists(sc_exe):
        return None, None

    query = RUN_COMMAND([sc_exe, "query", name])
    if query.code != 0:
        return None, None

    state_match = re.search(r"STATE\s*:\s*\d+\s+([A-Z_]+)", query.out)
    state = state_match.group(1) if state_match else None

    qc = RUN_COMMAND([sc_exe, "qc", name])
    start_type = None
    if qc.code == 0:
        start_match = re.search(r"START_TYPE\s*:\s*\d+\s+([A-Z_]+)", qc.out)
        start_type = start_match.group(1) if start_match else None

    return state, start_type


def defender_service_status() -> Optional[str]:
    """Return ``RUNNING`` or ``STOPPED`` for WinDefend, else ``None``."""

    state, _ = _service_query("WinDefend")
    return state


def ensure_defender_autostart() -> bool:
    """Set WinDefend to AUTO_START using ``sc.exe``."""

    sc_exe = platform_state.SC_EXE
    if (
        not platform_state.IS_WINDOWS
        or not is_admin()
        or not sc_exe
        or not os.path.exists(sc_exe)
    ):
        return False
    res = RUN_COMMAND([sc_exe, "config", "WinDefend", "start=", "auto"])
    if res.code != 0:
        return False
    _, start_type = _service_query("WinDefend")
    return start_type == "AUTO_START"


def start_defender_service() -> bool:
    """Start WinDefend service if not running."""

    sc_exe = platform_state.SC_EXE
    if (
        not platform_state.IS_WINDOWS
        or not is_admin()
        or not sc_exe
        or not os.path.exists(sc_exe)
    ):
        return False
    state = defender_service_status()
    if state == "RUNNING":
        return True
    res = RUN_COMMAND([sc_exe, "start", "WinDefend"])
    return res.code == 0


def stop_defender_service() -> bool:
    """Stop WinDefend service if running."""

    sc_exe = platform_state.SC_EXE
    if (
        not platform_state.IS_WINDOWS
        or not is_admin()
        or not sc_exe
        or not os.path.exists(sc_exe)
    ):
        return False
    state = defender_service_status()
    if state == "STOPPED":
        return True
    res = RUN_COMMAND([sc_exe, "stop", "WinDefend"])
    return res.code == 0


def detect_defender_blockers() -> tuple[str, ...]:
    """Return potential actors preventing Defender changes."""

    if not platform_state.IS_WINDOWS:
        return ()
    diag = guarded_call(
        defender_utils.get_defender_status,
        defender_utils.DefenderStatus(
            realtime=None,
            tamper_on=None,
            cmdlets_available=False,
            services_ok=False,
            third_party_av_present=False,
            policy_lock=False,
            services_error=None,
            error=None,
            third_party_names=(),
        ),
    )
    blockers: list[str] = []
    if diag.tamper_on:
        blockers.append("Tamper Protection")
    if diag.policy_lock:
        blockers.append("Policy Lock (GPO/MDM)")
    if diag.third_party_av_present:
        if diag.third_party_names:
            blockers.extend(diag.third_party_names)
        else:
            blockers.append("Third-party antivirus")
    if not diag.services_ok and diag.services_error:
        blockers.append(diag.services_error)
    if not diag.cmdlets_available:
        blockers.append("Defender PowerShell cmdlets unavailable")
    return dedupe(blockers)


def _collect_defender_blockers(
    ctx: OutcomeBuilder,
    *,
    run_result: Optional[RunResult] = None,
    status: Optional[DefenderStatus] = None,
) -> tuple[str, ...]:
    snapshot = status or guarded_call(
        get_defender_status,
        DefenderStatus(None, None, None, None, None, ()),
    )
    if snapshot.service_state:
        ctx.log.add("WinDefend", f"service_state={snapshot.service_state}")
    if snapshot.tamper_protection is not None:
        ctx.log.add("Tamper", "on" if snapshot.tamper_protection else "off")
    if snapshot.blockers:
        ctx.log.add("status blockers", ", ".join(snapshot.blockers))

    blockers = list(detect_defender_blockers())
    if snapshot.blockers:
        blockers.extend(snapshot.blockers)
    if run_result and run_result.err and "access is denied" in run_result.err.lower():
        blockers.append("Access denied (permissions)")
    if run_result:
        combined = " ".join(
            part.lower() for part in (run_result.err, run_result.out) if part
        )
        if "tamper" in combined:
            blockers.append("Tamper Protection")
        if "policy" in combined and "lock" in combined:
            blockers.append("Policy Lock (GPO/MDM)")
        if "third" in combined and "antivirus" in combined:
            blockers.append("Third-party antivirus")
        if "service" in combined and "windefend" in combined:
            blockers.append("WinDefend service")
    return tuple(dedupe(blockers))


def get_defender_status() -> DefenderStatus:
    """Query Defender using ``Get-MpComputerStatus``."""

    if not platform_state.IS_WINDOWS:
        return DefenderStatus(None, None, None, None, None, ())

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
    rr = RUN_POWERSHELL(ps)
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
    diag = guarded_call(
        defender_utils.get_defender_status,
        defender_utils.DefenderStatus(
            realtime=None,
            tamper_on=None,
            cmdlets_available=False,
            services_ok=False,
            third_party_av_present=False,
            policy_lock=False,
            services_error=None,
            error=None,
            third_party_names=(),
        ),
    )
    blockers = list(detect_defender_blockers())
    if diag.third_party_names:
        blockers.extend(diag.third_party_names)
    if diag.policy_lock:
        blockers.append("Policy Lock (GPO/MDM)")
    return DefenderStatus(
        service_state=defender_service_status(),
        realtime_enabled=realtime,
        antispyware_enabled=antispy,
        antivirus_enabled=anti,
        tamper_protection=tamper,
        blockers=tuple(dedupe(blockers)),
    )


def set_defender_realtime(enabled: bool) -> ActionOutcome:
    """Toggle Defender real-time protection with diagnostics and fallbacks."""

    plan, blocked = build_toggle_plan(
        "defender_realtime",
        platform_detail="Defender realtime unavailable on this platform.",
        admin_message="Run Security Center as Administrator to change Defender settings.",
        probe=lambda: guarded_call(lambda: get_defender_status().realtime_enabled, None),
        expected=enabled,
    )
    if blocked:
        return blocked
    assert plan is not None
    ctx = plan.ctx
    pipeline = TogglePipeline(plan)

    disable_flag = "True" if not enabled else "False"
    ps = (
        "$ErrorActionPreference='Stop';"
        f" Set-MpPreference -DisableRealtimeMonitoring {disable_flag} -Force"
    )

    pipeline.add_command(
        "Set-MpPreference",
        lambda: RUN_POWERSHELL(ps),
        success_log="realtime matches request after Set-MpPreference",
        mismatch_log="Set-MpPreference reported success but realtime disagreed",
        failure_log="Set-MpPreference failed with rc={code}",
        attempts=2,
        retry_hint=("Set-MpPreference", "retrying enforcement after mismatch"),
        retry_label=lambda base, attempt: f"{base} (retry)",
    ).add_boolean(
        "defender_utils.set_defender_enabled",
        lambda: defender_utils.set_defender_enabled(enabled),
        success_log="realtime matches after defender_utils fallback",
        mismatch_log="defender_utils fallback reported success but realtime disagreed",
    ).add_verification(
        "realtime eventually matched requested state",
    )

    outcome = pipeline.execute()
    if outcome:
        return outcome

    ctx.add_blockers(*_collect_defender_blockers(ctx, run_result=pipeline.last_run))

    if not ctx.blockers:
        ctx.add_blockers("Unknown Defender blocker")

    return ctx.blocked("Defender realtime unchanged.")


def is_defender_realtime_on() -> Optional[bool]:
    return get_defender_status().realtime_enabled


def set_defender_enabled(enabled: bool) -> ActionOutcome:
    """Orchestrate Defender enable/disable with verification and reports."""

    plan, blocked = build_toggle_plan(
        "defender_master",
        platform_detail="Defender control unavailable on this platform.",
        admin_message="Run Security Center as Administrator to manage Defender.",
        probe=lambda: guarded_call(lambda: get_defender_status().realtime_enabled, None),
        expected=enabled,
    )
    if blocked:
        return blocked
    assert plan is not None
    ctx = plan.ctx

    probe_service = lambda: defender_service_status()

    if enabled:
        auto_ok = ensure_defender_autostart()
        ctx.log.add("ensure_defender_autostart", "ok" if auto_ok else "failed")
        if not auto_ok:
            ctx.add_blockers("WinDefend auto-start policy")

        started = drive_service_state(
            ctx,
            label="start WinDefend",
            runner=start_defender_service,
            probe=probe_service,
            expected="RUNNING",
            success_log="service running",
            mismatch_log="start reported but verification failed",
            blocker_label="WinDefend service",
        )
        if not started:
            ctx.log.add("start WinDefend", "retrying enforcement")
            drive_service_state(
                ctx,
                label="start WinDefend (retry)",
                runner=start_defender_service,
                probe=probe_service,
                expected="RUNNING",
                success_log="service running",
                mismatch_log="retry reported success but verification failed",
                blocker_label="WinDefend service",
            )

        realtime_pipeline = TogglePipeline(plan)
        realtime_pipeline.add_outcome(
            "set_defender_realtime(True)",
            lambda: set_defender_realtime(True),
            success_log="realtime confirmed running",
            success_detail="Defender realtime verified running.",
            mismatch_log="realtime still mismatched after realtime enable attempt",
        ).add_verification(
            "realtime eventually matched requested state",
            success_detail="Defender realtime verified running.",
        )

        rt_outcome = realtime_pipeline.execute()
        if rt_outcome:
            return rt_outcome

        status = guarded_call(
            get_defender_status,
            DefenderStatus(None, None, None, None, None, ()),
        )
        ctx.add_blockers(*_collect_defender_blockers(ctx, status=status))

        if not ctx.blockers:
            ctx.add_blockers("Unknown Defender blocker")
        return ctx.blocked()

    stopped = drive_service_state(
        ctx,
        label="stop WinDefend",
        runner=stop_defender_service,
        probe=probe_service,
        expected="STOPPED",
        success_log="service stopped",
        mismatch_log="stop reported but service still running",
        blocker_label="WinDefend service",
    )
    if not stopped:
        ctx.log.add("stop WinDefend", "retrying enforcement")
        drive_service_state(
            ctx,
            label="stop WinDefend (retry)",
            runner=stop_defender_service,
            probe=probe_service,
            expected="STOPPED",
            success_log="service stopped",
            mismatch_log="retry reported success but service still running",
            blocker_label="WinDefend service",
        )

    realtime_pipeline = TogglePipeline(plan)
    realtime_pipeline.add_outcome(
        "set_defender_realtime(False)",
        lambda: set_defender_realtime(False),
        success_log="realtime confirmed disabled",
        success_detail="Realtime monitoring disabled.",
        mismatch_log="realtime still mismatched after realtime disable attempt",
    ).add_verification(
        "realtime eventually matched requested state",
        success_detail="Realtime monitoring disabled.",
    )

    rt_outcome = realtime_pipeline.execute()
    if rt_outcome:
        return rt_outcome

    status = guarded_call(
        get_defender_status,
        DefenderStatus(None, None, None, None, None, ()),
    )
    ctx.add_blockers(*_collect_defender_blockers(ctx, status=status))

    if not ctx.blockers:
        ctx.add_blockers("Unknown Defender blocker")
    return ctx.blocked()


__all__ = [
    "defender_service_status",
    "detect_defender_blockers",
    "ensure_defender_autostart",
    "get_defender_status",
    "is_defender_realtime_on",
    "set_defender_enabled",
    "set_defender_realtime",
    "start_defender_service",
    "stop_defender_service",
]
