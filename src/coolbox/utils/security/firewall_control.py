"""Firewall orchestration built on top of the shared security core."""
from __future__ import annotations

import os
from typing import Optional

from . import firewall as firewall_utils
from . import platform as platform_state
from .core import (
    ActionOutcome,
    OutcomeBuilder,
    RunResult,
    TogglePipeline,
    build_toggle_plan,
    dedupe,
    guarded_call,
    run_command,
)


def is_firewall_enabled() -> Optional[bool]:
    """Return ``True`` if all profiles are enabled, ``False`` if any disabled."""

    if platform_state.IS_MAC:
        return firewall_utils.is_firewall_enabled()
    if not platform_state.IS_WINDOWS:
        return None
    if not platform_state.NETSH_EXE or not os.path.exists(platform_state.NETSH_EXE):
        return None

    result = RUN_COMMAND(
        [platform_state.NETSH_EXE, "advfirewall", "show", "allprofiles"], timeout=30
    )
    if result.code != 0:
        return None
    out = result.out.lower()
    return "state on" in out and "state off" not in out


def set_firewall_enabled(enabled: bool) -> ActionOutcome:
    """Toggle the Windows firewall or fall back to the macOS implementation."""

    if platform_state.IS_MAC:
        current = firewall_utils.is_firewall_enabled()
        if current is None:
            return ActionOutcome.blocked(("firewall unavailable",), "Unable to determine macOS firewall state.")
        if current == enabled:
            return ActionOutcome.ok("Already in requested state")
        ok, err = firewall_utils.set_firewall_enabled(enabled)
        if ok:
            return ActionOutcome.ok(err)
        detail = err or "Failed to toggle macOS firewall"
        return ActionOutcome.blocked(("toggle failed",), detail)

    plan, blocked = build_toggle_plan(
        "firewall",
        platform_detail="Firewall control unavailable on this platform.",
        admin_message="Run Security Center as Administrator to control the firewall.",
        probe=lambda: is_firewall_enabled(),
        expected=enabled,
    )
    if blocked:
        return blocked
    assert plan is not None
    ctx = plan.ctx
    pipeline = TogglePipeline(plan)

    if not platform_state.NETSH_EXE or not os.path.exists(platform_state.NETSH_EXE):
        ctx.log.add("netsh", "executable missing")
        ctx.add_blockers("netsh.exe missing")
        return ctx.blocked("netsh executable not found. Cannot toggle firewall.")

    state = "on" if enabled else "off"
    cmd = [platform_state.NETSH_EXE, "advfirewall", "set", "allprofiles", "state", state]
    label = f"netsh advfirewall set allprofiles state {state}"
    pipeline.add_command(
        label,
        lambda: RUN_COMMAND(cmd, timeout=45),
        success_log="profiles match request after netsh",
        mismatch_log="netsh reported success but profiles disagreed",
        failure_log="netsh failed with rc={code}",
        attempts=2,
        retry_hint=("netsh", "reissuing enforcement after mismatch"),
        retry_label=lambda base, attempt: f"{base} (retry)",
    ).add_boolean(
        "firewall_utils.set_firewall_enabled",
        lambda: firewall_utils.set_firewall_enabled(enabled),
        success_log="profiles match after firewall_utils fallback",
        mismatch_log="firewall_utils fallback reported success but profiles disagreed",
    ).add_verification(
        "profiles eventually matched requested state",
    )

    outcome = pipeline.execute()
    if outcome:
        return outcome

    if pipeline.last_run:
        ctx.add_blockers(*_collect_firewall_blockers(ctx, pipeline.last_run))

    if not ctx.blockers:
        ctx.add_blockers("Unknown firewall blocker")

    return ctx.blocked("Firewall state unchanged.")


def detect_firewall_blockers() -> tuple[str, ...]:
    """Return potential actors preventing firewall changes."""

    if platform_state.IS_MAC:
        status = guarded_call(
            firewall_utils.get_firewall_status,
            firewall_utils.FirewallStatus(
                domain=None,
                private=None,
                public=None,
                services_ok=True,
                cmdlets_available=False,
                policy_lock=False,
                third_party_firewall=False,
                services_error=None,
                error=None,
            ),
        )
        blockers: list[str] = []
        if status.mac_defaults_available is False and status.mac_socketfilterfw_available is False:
            blockers.append("macOS firewall tools missing")
        if status.mac_socketfilterfw_available is False and status.mac_defaults_available is not False:
            blockers.append("socketfilterfw tool missing")
        if status.mac_defaults_available is False and status.mac_socketfilterfw_available is not False:
            blockers.append("defaults tool missing")
        if status.mac_defaults_usable is False and status.mac_defaults_available:
            blockers.append("defaults tool not executable")
        if status.mac_socketfilterfw_usable is False and status.mac_socketfilterfw_available:
            blockers.append("socketfilterfw tool not executable")
        if status.mac_defaults_plist_damaged:
            blockers.append(
                status.mac_defaults_plist_parse_error
                or "com.apple.alf.plist contains invalid data"
            )
        if (
            status.mac_defaults_plist_available is False
            and status.mac_defaults_plist_bootstrap_supported is False
            and status.mac_defaults_plist_bootstrap_error
        ):
            blockers.append(status.mac_defaults_plist_bootstrap_error)
        if status.mac_launchctl_available is False and status.mac_defaults_plist_bootstrap_supported:
            blockers.append("launchctl tool missing")
        if status.mac_launchctl_available and status.mac_launchctl_usable is False:
            blockers.append("launchctl tool not executable")
        if (
            status.mac_launchctl_available
            and status.mac_launchctl_label_available is False
        ):
            blockers.append("com.apple.alf.agent launchd plist missing")
        if (
            status.mac_launchctl_available
            and status.mac_launchctl_usable
            and status.mac_launchctl_kickstart_supported is False
        ):
            blockers.append("launchctl kickstart unsupported")
        if status.mac_admin is False:
            blockers.append("Administrator privileges required (sudo root access)")
        if status.error:
            blockers.append(status.error)
        if status.mac_tool_errors:
            blockers.extend(status.mac_tool_errors)
        if status.mac_launchctl_errors:
            blockers.extend(status.mac_launchctl_errors)
        return tuple(dedupe(blockers))

    if not platform_state.IS_WINDOWS:
        return ()
    status = guarded_call(
        firewall_utils.get_firewall_status,
        firewall_utils.FirewallStatus(
            domain=None,
            private=None,
            public=None,
            services_ok=False,
            cmdlets_available=False,
            policy_lock=False,
            third_party_firewall=False,
            services_error=None,
            error=None,
            third_party_names=(),
        ),
    )
    blockers: list[str] = []
    if status.policy_lock:
        blockers.append("Policy Lock (GPO/MDM)")
    if status.third_party_firewall:
        if status.third_party_names:
            blockers.extend(status.third_party_names)
        else:
            blockers.append("Third-party firewall")
    if not status.services_ok and status.services_error:
        blockers.append(status.services_error)
    return dedupe(blockers)


def _collect_firewall_blockers(ctx: OutcomeBuilder, last_run: RunResult) -> tuple[str, ...]:
    status = guarded_call(
        firewall_utils.get_firewall_status,
        firewall_utils.FirewallStatus(
            domain=None,
            private=None,
            public=None,
            services_ok=False,
            cmdlets_available=False,
            policy_lock=False,
            third_party_firewall=False,
            services_error=None,
            error=None,
            third_party_names=(),
        ),
    )
    ctx.log.add(
        "profile snapshot",
        f"domain={status.domain} private={status.private} public={status.public}",
    )
    if status.services_error:
        ctx.log.add("services", status.services_error)
    if status.error and status.error != status.services_error:
        ctx.log.add("error", status.error)
    if status.third_party_names:
        ctx.log.add("third-party", ", ".join(status.third_party_names))

    blockers = list(detect_firewall_blockers())
    if status.policy_lock and "Policy Lock (GPO/MDM)" not in blockers:
        blockers.append("Policy Lock (GPO/MDM)")
    if status.third_party_firewall and not status.third_party_names:
        blockers.append("Third-party firewall")

    blockers = list(dedupe(blockers))
    if not blockers:
        combined = " ".join(
            res_part.lower() for res_part in (last_run.err, last_run.out) if res_part
        )
        if "access is denied" in combined:
            blockers.append("Access denied (permissions)")
        if "group policy" in combined or "gpo" in combined:
            blockers.append("Policy Lock (GPO/MDM)")
        if "third" in combined and "firewall" in combined:
            blockers.append("Third-party firewall")
        if "mpssvc" in combined or "windows firewall service" in combined:
            blockers.append("Windows Firewall service")
        if "another program" in combined and "firewall" in combined:
            blockers.append("Third-party firewall")
    return tuple(dedupe(blockers))


__all__ = [
    "detect_firewall_blockers",
    "is_firewall_enabled",
    "set_firewall_enabled",
]
RUN_COMMAND = run_command
