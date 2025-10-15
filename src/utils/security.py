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
import time
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple, TypeVar, Protocol

from src.app import error_handler as eh
from src.utils import defender as defender_utils
from src.utils import firewall as firewall_utils


# ----------------------------- Platform guard ------------------------------

_IS_WINDOWS = platform.system() == "Windows"

# Creation flags to suppress any console windows on Windows
CREATE_NO_WINDOW = 0x08000000 if _IS_WINDOWS else 0

# Path to sc.exe to avoid PowerShell alias collision with Set-Content
_SC_EXE = r"C:\\Windows\\System32\\sc.exe" if _IS_WINDOWS else None
_NETSH_EXE = r"C:\\Windows\\System32\\netsh.exe" if _IS_WINDOWS else None
_POWERSHELL_EXE = (
    r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" if _IS_WINDOWS else None
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
    """Return True if running with administrative privileges."""
    return is_admin()


def relaunch_security_center(args: Optional[List[str]] = None) -> bool:
    """Relaunch Security Center with elevation if possible.

    Returns ``True`` if a relaunch was attempted. On non-Windows platforms or
    when already running as administrator, ``False`` is returned immediately.
    """
    if not _IS_WINDOWS or is_admin():
        return False
    try:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "security_center_hidden.py"
        )
        if not script.exists():
            return False
        params = " ".join(
            f'"{p}"' for p in [str(script), *(args or [])]
        )
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        return rc > 32
    except Exception:
        return False


# ------------------------------ Run helpers --------------------------------


@dataclass(frozen=True)
class RunResult:
    code: int
    out: str
    err: str


@dataclass(frozen=True)
class ActionOutcome:
    """Result of a privileged toggle attempt."""

    success: bool
    blockers: tuple[str, ...] = ()
    detail: Optional[str] = None

    @classmethod
    def ok(cls, detail: Optional[str] = None) -> "ActionOutcome":
        return cls(True, (), detail)

    @classmethod
    def blocked(
        cls, blockers: Iterable[str], detail: Optional[str] = None
    ) -> "ActionOutcome":
        ordered = tuple(dict.fromkeys([b for b in blockers if b]))
        return cls(False, ordered, detail)

    def merge_detail(self, extra: Optional[str]) -> "ActionOutcome":
        if not extra:
            return self
        if self.detail:
            return ActionOutcome(self.success, self.blockers, f"{self.detail} | {extra}")
        return ActionOutcome(self.success, self.blockers, extra)


class _ActionLog:
    """Compact recorder for the steps taken to enforce a state."""

    __slots__ = ("_steps",)

    def __init__(self) -> None:
        self._steps: list[str] = []

    def add(self, label: str, outcome: Optional[str] = None) -> None:
        if outcome:
            self._steps.append(f"{label}: {outcome}")
        else:
            self._steps.append(label)

    def extend(self, values: Iterable[str]) -> None:
        for value in values:
            if value:
                self._steps.append(value)

    def render(self) -> Optional[str]:
        if not self._steps:
            return None
        return " | ".join(self._steps)


_lock = threading.RLock()


class _OutcomeBuilder:
    """Utility to compose :class:`ActionOutcome` objects consistently."""

    __slots__ = ("feature", "log", "blockers", "_extra_detail")

    def __init__(self, feature: str) -> None:
        self.feature = feature
        self.log = _ActionLog()
        self.blockers: list[str] = []
        self._extra_detail: list[str] = []

    def require_windows(self, unavailable_detail: str) -> Optional[ActionOutcome]:
        if _IS_WINDOWS:
            return None
        self.log.add("platform", "non-Windows host")
        return ActionOutcome.ok(self._compose_detail(unavailable_detail))

    def require_admin(self, reason: str, message: str) -> Optional[ActionOutcome]:
        if is_admin():
            return None
        return ActionOutcome.blocked([reason], message)

    def record_run(self, label: str, result: RunResult) -> None:
        self.log.add(label, f"rc={result.code}")
        self.log.extend(part for part in (result.err, result.out) if part)

    def merge_detail(self, detail: Optional[str]) -> None:
        if detail:
            self._extra_detail.append(detail)

    def add_blockers(self, *candidates: str) -> None:
        for candidate in candidates:
            if candidate and candidate not in self.blockers:
                self.blockers.append(candidate)

    def chain_outcome(self, label: str, outcome: ActionOutcome) -> None:
        display = outcome.detail or ("ok" if outcome.success else "blocked")
        if label:
            self.log.add(label, display)
        if not outcome.success:
            self.add_blockers(*outcome.blockers)
            self.merge_detail(outcome.detail)

    def success(self, default_detail: Optional[str] = None) -> ActionOutcome:
        return ActionOutcome.ok(self._compose_detail(default_detail))

    def blocked(self, default_detail: Optional[str] = None) -> ActionOutcome:
        blockers = _dedupe(self.blockers)
        return ActionOutcome.blocked(blockers, self._compose_detail(default_detail))

    def _compose_detail(self, default_detail: Optional[str]) -> Optional[str]:
        parts = [self.log.render(), *self._extra_detail]
        filtered = [part for part in parts if part]
        if filtered:
            return " | ".join(filtered)
        return default_detail


class _FeatureAction:
    """Helper that centralizes platform and privilege gating for a feature."""

    __slots__ = ("ctx", "_blocked")

    def __init__(
        self,
        feature: str,
        *,
        platform_detail: str,
        admin_message: str,
        admin_reason: str = "Administrator privileges required",
    ) -> None:
        ctx = _OutcomeBuilder(feature)
        gated = ctx.require_windows(platform_detail)
        if gated:
            self.ctx = ctx
            self._blocked = gated
            return
        gated = ctx.require_admin(admin_reason, admin_message)
        self.ctx = ctx
        self._blocked = gated

    @property
    def blocked(self) -> Optional[ActionOutcome]:
        return self._blocked


class _StateEnforcer:
    """Drive a stateful toggle with shared verification semantics."""

    __slots__ = ("ctx", "probe", "expected")

    def __init__(
        self,
        ctx: _OutcomeBuilder,
        probe: Callable[[], Optional[bool]],
        expected: bool,
    ) -> None:
        self.ctx = ctx
        self.probe = probe
        self.expected = expected

    def _verify(
        self,
        success_log: str,
        *,
        detail: Optional[str] = None,
        default_detail: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        if _wait_for_state(self.probe, self.expected):
            if success_log:
                self.ctx.log.add("verification", success_log)
            return self.ctx.success(detail or default_detail)
        return None

    def run_command(
        self,
        label: str,
        runner: Callable[[], RunResult],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
        failure_log: Optional[str] = None,
    ) -> tuple[RunResult, Optional[ActionOutcome]]:
        result = runner()
        self.ctx.record_run(label, result)
        outcome = None
        if result.code == 0:
            outcome = self._verify(success_log, detail=success_detail)
            if outcome is None and mismatch_log:
                self.ctx.log.add("verification", mismatch_log)
        elif failure_log:
            if "{code}" in failure_log:
                self.ctx.log.add("verification", failure_log.format(code=result.code))
            else:
                self.ctx.log.add("verification", failure_log)
        return result, outcome

    def run_boolean(
        self,
        label: str,
        runner: Callable[[], Tuple[bool, Optional[str]]],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        ok, detail = runner()
        self.ctx.log.add(label, "ok" if ok else f"failed ({detail or 'no detail'})")
        if detail:
            self.ctx.merge_detail(detail)
        if ok:
            outcome = self._verify(success_log, detail=success_detail)
            if outcome is None and mismatch_log:
                self.ctx.log.add("verification", mismatch_log)
            return outcome
        return None

    def run_outcome(
        self,
        label: str,
        runner: Callable[[], ActionOutcome],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        outcome = runner()
        self.ctx.chain_outcome(label, outcome)
        if outcome.success:
            verified = self._verify(success_log, detail=success_detail)
            if verified is None and mismatch_log:
                self.ctx.log.add("verification", mismatch_log)
            return verified
        return None

    def verify_eventual(
        self,
        success_log: str,
        *,
        success_detail: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        return self._verify(success_log, detail=success_detail)


class _TogglePlan:
    """Bundle a feature context with the shared state enforcer."""

    __slots__ = ("ctx", "enforcer")

    def __init__(
        self,
        ctx: _OutcomeBuilder,
        probe: Callable[[], Optional[bool]],
        expected: bool,
    ) -> None:
        self.ctx = ctx
        self.enforcer = _StateEnforcer(ctx, probe, expected)

    def run_command(
        self,
        label: str,
        runner: Callable[[], RunResult],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
        failure_log: Optional[str] = None,
    ) -> tuple[RunResult, Optional[ActionOutcome]]:
        return self.enforcer.run_command(
            label,
            runner,
            success_log=success_log,
            success_detail=success_detail,
            mismatch_log=mismatch_log,
            failure_log=failure_log,
        )

    def run_boolean(
        self,
        label: str,
        runner: Callable[[], Tuple[bool, Optional[str]]],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        return self.enforcer.run_boolean(
            label,
            runner,
            success_log=success_log,
            success_detail=success_detail,
            mismatch_log=mismatch_log,
        )

    def run_outcome(
        self,
        label: str,
        runner: Callable[[], ActionOutcome],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        return self.enforcer.run_outcome(
            label,
            runner,
            success_log=success_log,
            success_detail=success_detail,
            mismatch_log=mismatch_log,
        )

    def verify_eventual(
        self,
        success_log: str,
        *,
        success_detail: Optional[str] = None,
    ) -> Optional[ActionOutcome]:
        return self.enforcer.verify_eventual(
            success_log,
            success_detail=success_detail,
        )


class _PipelineState:
    """Mutable state shared across pipeline steps."""

    __slots__ = ("plan", "last_run")

    def __init__(self, plan: _TogglePlan) -> None:
        self.plan = plan
        self.last_run: Optional[RunResult] = None

    def record_run(self, result: RunResult) -> None:
        self.last_run = result

    def reset(self) -> None:
        self.last_run = None


class _PipelineStep(Protocol):
    def execute(self, state: "_PipelineState") -> Optional[ActionOutcome]:
        ...


@dataclass(frozen=True)
class _CommandStep:
    label: str
    runner: Callable[[], RunResult]
    success_log: str
    success_detail: Optional[str]
    mismatch_log: Optional[str]
    failure_log: Optional[str]
    attempts: int
    retry_hint: Optional[tuple[str, str]]
    retry_label: Optional[Callable[[str, int], str]]

    def execute(self, state: _PipelineState) -> Optional[ActionOutcome]:
        attempts = self.attempts if self.attempts > 0 else 1
        label_builder: Callable[[str, int], str]
        if self.retry_label:
            label_builder = self.retry_label
        else:
            label_builder = lambda base, attempt: f"{base} (retry {attempt})"
        last_result: Optional[RunResult] = None
        for attempt in range(attempts):
            current_label = self.label if attempt == 0 else label_builder(self.label, attempt)
            result, outcome = state.plan.run_command(
                current_label,
                self.runner,
                success_log=self.success_log,
                success_detail=self.success_detail,
                mismatch_log=self.mismatch_log,
                failure_log=self.failure_log,
            )
            last_result = result
            state.record_run(result)
            if outcome:
                return outcome
            if result.code != 0:
                break
            if attempt < attempts - 1 and self.retry_hint:
                hint_label, hint_message = self.retry_hint
                state.plan.ctx.log.add(hint_label, hint_message)
        if last_result is not None:
            state.record_run(last_result)
        return None


@dataclass(frozen=True)
class _BooleanStep:
    label: str
    runner: Callable[[], Tuple[bool, Optional[str]]]
    success_log: str
    success_detail: Optional[str]
    mismatch_log: Optional[str]

    def execute(self, state: _PipelineState) -> Optional[ActionOutcome]:
        return state.plan.run_boolean(
            self.label,
            self.runner,
            success_log=self.success_log,
            success_detail=self.success_detail,
            mismatch_log=self.mismatch_log,
        )


@dataclass(frozen=True)
class _OutcomeStep:
    label: str
    runner: Callable[[], ActionOutcome]
    success_log: str
    success_detail: Optional[str]
    mismatch_log: Optional[str]

    def execute(self, state: _PipelineState) -> Optional[ActionOutcome]:
        return state.plan.run_outcome(
            self.label,
            self.runner,
            success_log=self.success_log,
            success_detail=self.success_detail,
            mismatch_log=self.mismatch_log,
        )


@dataclass(frozen=True)
class _VerifyStep:
    success_log: str
    success_detail: Optional[str]

    def execute(self, state: _PipelineState) -> Optional[ActionOutcome]:
        return state.plan.verify_eventual(
            self.success_log,
            success_detail=self.success_detail,
        )


class _TogglePipeline:
    """Coordinate sequential enforcement attempts for a toggle."""

    __slots__ = ("_state", "_steps", "_final")

    def __init__(self, plan: _TogglePlan) -> None:
        self._state = _PipelineState(plan)
        self._steps: List[_PipelineStep] = []
        self._final: Optional[ActionOutcome] = None

    def add_command(
        self,
        label: str,
        runner: Callable[[], RunResult],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
        failure_log: Optional[str] = None,
        attempts: int = 1,
        retry_hint: Optional[tuple[str, str]] = None,
        retry_label: Optional[Callable[[str, int], str]] = None,
    ) -> "_TogglePipeline":
        self._steps.append(
            _CommandStep(
                label,
                runner,
                success_log,
                success_detail,
                mismatch_log,
                failure_log,
                attempts if attempts > 0 else 1,
                retry_hint,
                retry_label,
            )
        )
        return self

    def add_boolean(
        self,
        label: str,
        runner: Callable[[], Tuple[bool, Optional[str]]],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
    ) -> "_TogglePipeline":
        self._steps.append(
            _BooleanStep(label, runner, success_log, success_detail, mismatch_log)
        )
        return self

    def add_outcome(
        self,
        label: str,
        runner: Callable[[], ActionOutcome],
        *,
        success_log: str,
        success_detail: Optional[str] = None,
        mismatch_log: Optional[str] = None,
    ) -> "_TogglePipeline":
        self._steps.append(
            _OutcomeStep(label, runner, success_log, success_detail, mismatch_log)
        )
        return self

    def add_verification(
        self,
        success_log: str,
        *,
        success_detail: Optional[str] = None,
    ) -> "_TogglePipeline":
        self._steps.append(_VerifyStep(success_log, success_detail))
        return self

    def execute(self) -> Optional[ActionOutcome]:
        self._final = None
        for step in list(self._steps):
            outcome = step.execute(self._state)
            if outcome:
                self._final = outcome
                break
        self._steps.clear()
        return self._final

    def reset(self) -> None:
        self._steps.clear()
        self._final = None
        self._state.reset()

    @property
    def plan(self) -> _TogglePlan:
        return self._state.plan

    @property
    def last_run(self) -> Optional[RunResult]:
        return self._state.last_run


def _build_toggle(
    feature: str,
    *,
    platform_detail: str,
    admin_message: str,
    probe: Callable[[], Optional[bool]],
    expected: bool,
    admin_reason: str = "Administrator privileges required",
) -> tuple[Optional[_TogglePlan], Optional[ActionOutcome]]:
    action = _FeatureAction(
        feature,
        platform_detail=platform_detail,
        admin_message=admin_message,
        admin_reason=admin_reason,
    )
    if action.blocked:
        return None, action.blocked
    plan = _TogglePlan(action.ctx, probe, expected)
    return plan, None


def _drive_service_state(
    ctx: _OutcomeBuilder,
    *,
    label: str,
    runner: Callable[[], bool],
    probe: Callable[[], Optional[str]],
    expected: str,
    success_log: str,
    mismatch_log: str,
    blocker_label: str,
) -> bool:
    ok = runner()
    if ok and _wait_for_service_state(probe, expected):
        ctx.log.add(label, success_log)
        return True
    if ok:
        ctx.log.add(label, mismatch_log)
        ctx.add_blockers(blocker_label)
        return False
    ctx.log.add(label, "failed")
    ctx.add_blockers(blocker_label)
    return False


def _run(cmd: List[str], timeout: int = 30) -> RunResult:
    """Run a command with no visible window. Returns stdout, stderr, code."""
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


T = TypeVar("T")


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys([it for it in items if it]))


def _guarded_call(func: Callable[[], T], fallback: T) -> T:
    """Execute *func* and fall back gracefully on unexpected errors."""

    try:
        return func()
    except Exception as exc:  # pragma: no cover - defensive logging only
        eh.handle_exception(type(exc), exc, exc.__traceback__)
        return fallback


def _wait_for_state(
    probe: Callable[[], Optional[bool]],
    expected: bool,
    *,
    attempts: int = 6,
    base_delay: float = 0.35,
) -> bool:
    """Poll *probe* until it returns the expected boolean value."""

    for attempt in range(attempts):
        state = _guarded_call(probe, None)
        if state is None:
            time.sleep(base_delay * (attempt + 1))
            continue
        if (state is True) if expected else (state is False):
            return True
        time.sleep(base_delay * (attempt + 1))
    return False


def _wait_for_service_state(
    probe: Callable[[], Optional[str]],
    expected: str,
    *,
    attempts: int = 6,
    base_delay: float = 0.35,
) -> bool:
    """Poll *probe* until the service reaches *expected* state."""

    expected_upper = expected.upper()
    for attempt in range(attempts):
        state = _guarded_call(probe, None)
        if state and state.upper() == expected_upper:
            return True
        time.sleep(base_delay * (attempt + 1))
    return False


def run_command_background(
    cmd: List[str], **popen_kwargs
) -> Tuple[bool, Optional[subprocess.Popen]]:
    """Launch *cmd* in background. Returns (success, Popen)."""
    try:
        p = subprocess.Popen(cmd, **popen_kwargs)
        return True, p
    except Exception as e:  # pragma: no cover - popen failure
        eh.handle_exception(type(e), e, e.__traceback__)
        return False, None


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

    # Parse each profile block: "State ON/OFF"
    states = re.findall(r"State\s+(\w+)", res.out, flags=re.IGNORECASE)
    if not states:
        return None
    on_all = all(s.lower() in ("on", "enabled", "1") for s in states)
    return True if on_all else False


def set_firewall_enabled(enabled: bool) -> ActionOutcome:
    """Enable or disable firewall for all profiles with resilient fallbacks."""

    plan, blocked = _build_toggle(
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
    pipeline = _TogglePipeline(plan)

    if not _NETSH_EXE or not os.path.exists(_NETSH_EXE):
        ctx.log.add("netsh", "executable missing")
        ctx.add_blockers("netsh.exe missing")
        return ctx.blocked("netsh executable not found. Cannot toggle firewall.")

    state = "on" if enabled else "off"

    cmd = [_NETSH_EXE, "advfirewall", "set", "allprofiles", "state", state]
    label = f"netsh advfirewall set allprofiles state {state}"
    pipeline.add_command(
        label,
        lambda: _run(cmd, timeout=45),
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

    # STATE              : 4  RUNNING
    m_state = re.search(r"STATE\s*:\s*\d+\s+([A-Z_]+)", q.out)
    state = m_state.group(1) if m_state else None

    q2 = _run([_SC_EXE, "qc", name])
    start_type = None
    if q2.code == 0:
        # START_TYPE         : 2   AUTO_START
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
    # sc.exe uses a quirky syntax: "start= auto" must be split; above is safe.
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
        # It might already be starting; re-check
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


@dataclass(frozen=True)
class DefenderStatus:
    service_state: Optional[str]  # RUNNING/STOPPED
    realtime_enabled: Optional[bool]
    antispyware_enabled: Optional[bool]
    antivirus_enabled: Optional[bool]
    tamper_protection: Optional[bool]
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecuritySnapshot:
    """Aggregate view consumed by the Security Center UI."""

    admin: bool
    firewall_enabled: Optional[bool]
    defender: DefenderStatus
    firewall_blockers: tuple[str, ...] = ()


def detect_firewall_blockers() -> tuple[str, ...]:
    """Return potential actors preventing firewall changes."""

    if not _IS_WINDOWS:
        return ()
    status = _guarded_call(
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
    return _dedupe(blockers)


def _collect_firewall_blockers(ctx: _OutcomeBuilder, last_run: RunResult) -> tuple[str, ...]:
    status = _guarded_call(
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

    blockers = list(_dedupe(blockers))
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
    return tuple(_dedupe(blockers))


def detect_defender_blockers() -> tuple[str, ...]:
    """Return potential actors preventing Defender changes."""

    if not _IS_WINDOWS:
        return ()
    diag = _guarded_call(
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
    return _dedupe(blockers)


def _collect_defender_blockers(
    ctx: _OutcomeBuilder,
    *,
    run_result: Optional[RunResult] = None,
    status: Optional[DefenderStatus] = None,
) -> tuple[str, ...]:
    snapshot = status or _guarded_call(
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
    return tuple(_dedupe(blockers))


def get_defender_status() -> DefenderStatus:
    """
    Query Defender using Get-MpComputerStatus. Returns summarized booleans.
    """
    if not _IS_WINDOWS:
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
    diag = _guarded_call(
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
    return DefenderStatus(
        service_state=defender_service_status(),
        realtime_enabled=realtime,
        antispyware_enabled=antispy,
        antivirus_enabled=anti,
        tamper_protection=tamper,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def get_security_snapshot() -> SecuritySnapshot:
    """Collect a coherent snapshot for the Security Center dialog."""

    admin = _guarded_call(is_admin, False)
    firewall = _guarded_call(is_firewall_enabled, None)
    firewall_blockers = detect_firewall_blockers()
    defender = _guarded_call(
        get_defender_status,
        DefenderStatus(None, None, None, None, None, ()),
    )
    return SecuritySnapshot(
        admin=admin,
        firewall_enabled=firewall,
        defender=defender,
        firewall_blockers=firewall_blockers,
    )


def set_defender_realtime(enabled: bool) -> ActionOutcome:
    """Toggle Defender real-time protection with diagnostics and fallbacks."""

    plan, blocked = _build_toggle(
        "defender_realtime",
        platform_detail="Defender realtime unavailable on this platform.",
        admin_message="Run Security Center as Administrator to change Defender settings.",
        probe=lambda: _guarded_call(lambda: get_defender_status().realtime_enabled, None),
        expected=enabled,
    )
    if blocked:
        return blocked
    assert plan is not None
    ctx = plan.ctx
    pipeline = _TogglePipeline(plan)

    disable_flag = "True" if not enabled else "False"
    ps = (
        "$ErrorActionPreference='Stop';"
        f" Set-MpPreference -DisableRealtimeMonitoring {disable_flag} -Force"
    )

    pipeline.add_command(
        "Set-MpPreference",
        lambda: _run_ps(ps),
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


# -------------------------- Composite high-level API ------------------------


def is_defender_realtime_on() -> Optional[bool]:
    return get_defender_status().realtime_enabled


def set_defender_enabled(enabled: bool) -> ActionOutcome:
    """
    Orchestrate Defender enable/disable with hardened verification and reports.
    """

    probe_rt = lambda: _guarded_call(lambda: get_defender_status().realtime_enabled, None)
    plan, blocked = _build_toggle(
        "defender_master",
        platform_detail="Defender control unavailable on this platform.",
        admin_message="Run Security Center as Administrator to manage Defender.",
        probe=probe_rt,
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

        started = _drive_service_state(
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
            _drive_service_state(
                ctx,
                label="start WinDefend (retry)",
                runner=start_defender_service,
                probe=probe_service,
                expected="RUNNING",
                success_log="service running",
                mismatch_log="retry reported success but verification failed",
                blocker_label="WinDefend service",
            )

        realtime_pipeline = _TogglePipeline(plan)
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

        status = _guarded_call(
            get_defender_status,
            DefenderStatus(None, None, None, None, None, ()),
        )
        ctx.add_blockers(*_collect_defender_blockers(ctx, status=status))

        if not ctx.blockers:
            ctx.add_blockers("Unknown Defender blocker")
        return ctx.blocked()

    stopped = _drive_service_state(
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
        _drive_service_state(
            ctx,
            label="stop WinDefend (retry)",
            runner=stop_defender_service,
            probe=probe_service,
            expected="STOPPED",
            success_log="service stopped",
            mismatch_log="retry reported success but service still running",
            blocker_label="WinDefend service",
        )

    realtime_pipeline = _TogglePipeline(plan)
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

    status = _guarded_call(
        get_defender_status,
        DefenderStatus(None, None, None, None, None, ()),
    )
    ctx.add_blockers(*_collect_defender_blockers(ctx, status=status))

    if not ctx.blockers:
        ctx.add_blockers("Unknown Defender blocker")
    return ctx.blocked()


# ------------------------------ Module self-test ----------------------------


if __name__ == "__main__":
    print(f"Admin: {is_admin()}")
    print(f"Firewall enabled: {is_firewall_enabled()}")
    fw_res = set_firewall_enabled(True)
    print(f"Set firewall on: {fw_res.success} ({fw_res.detail})")
    print(f"Defender status: {get_defender_status()}")
    en_res = set_defender_enabled(True)
    print(f"Enable Defender: {en_res.success} ({en_res.detail})")
    dis_res = set_defender_realtime(False)
    print(f"Disable realtime: {dis_res.success} ({dis_res.detail})")

