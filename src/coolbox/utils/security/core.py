"""Core orchestration helpers shared across security controls."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Tuple, TypeVar

from . import platform as platform_state

T = TypeVar("T")


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


@dataclass(frozen=True)
class DefenderStatus:
    service_state: Optional[str]
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


class ActionLog:
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


class OutcomeBuilder:
    """Utility to compose :class:`ActionOutcome` objects consistently."""

    __slots__ = ("feature", "log", "blockers", "_extra_detail")

    def __init__(self, feature: str) -> None:
        self.feature = feature
        self.log = ActionLog()
        self.blockers: list[str] = []
        self._extra_detail: list[str] = []

    def require_windows(self, unavailable_detail: str) -> Optional[ActionOutcome]:
        if platform_state.IS_WINDOWS:
            return None
        self.log.add("platform", "non-Windows host")
        self.add_blockers("Unsupported platform")
        return self.blocked(unavailable_detail)

    def require_admin(self, reason: str, message: str) -> Optional[ActionOutcome]:
        from .admin import is_admin

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
        blockers = dedupe(self.blockers)
        return ActionOutcome.blocked(blockers, self._compose_detail(default_detail))

    def _compose_detail(self, default_detail: Optional[str]) -> Optional[str]:
        parts = [self.log.render(), *self._extra_detail]
        filtered = [part for part in parts if part]
        if filtered:
            return " | ".join(filtered)
        return default_detail


class FeatureAction:
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
        ctx = OutcomeBuilder(feature)
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


class StateEnforcer:
    """Drive a stateful toggle with shared verification semantics."""

    __slots__ = ("ctx", "probe", "expected")

    def __init__(
        self,
        ctx: OutcomeBuilder,
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
        if wait_for_state(self.probe, self.expected):
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


class TogglePlan:
    """Bundle a feature context with the shared state enforcer."""

    __slots__ = ("ctx", "enforcer")

    def __init__(
        self,
        ctx: OutcomeBuilder,
        probe: Callable[[], Optional[bool]],
        expected: bool,
    ) -> None:
        self.ctx = ctx
        self.enforcer = StateEnforcer(ctx, probe, expected)

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


class PipelineState:
    """Mutable state shared across pipeline steps."""

    __slots__ = ("plan", "last_run")

    def __init__(self, plan: TogglePlan) -> None:
        self.plan = plan
        self.last_run: Optional[RunResult] = None

    def record_run(self, result: RunResult) -> None:
        self.last_run = result

    def reset(self) -> None:
        self.last_run = None


class PipelineStep:
    def execute(self, state: PipelineState) -> Optional[ActionOutcome]:
        raise NotImplementedError


@dataclass(frozen=True)
class CommandStep(PipelineStep):
    label: str
    runner: Callable[[], RunResult]
    success_log: str
    success_detail: Optional[str]
    mismatch_log: Optional[str]
    failure_log: Optional[str]
    attempts: int
    retry_hint: Optional[tuple[str, str]]
    retry_label: Optional[Callable[[str, int], str]]

    def execute(self, state: PipelineState) -> Optional[ActionOutcome]:
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
class BooleanStep(PipelineStep):
    label: str
    runner: Callable[[], Tuple[bool, Optional[str]]]
    success_log: str
    success_detail: Optional[str]
    mismatch_log: Optional[str]

    def execute(self, state: PipelineState) -> Optional[ActionOutcome]:
        return state.plan.run_boolean(
            self.label,
            self.runner,
            success_log=self.success_log,
            success_detail=self.success_detail,
            mismatch_log=self.mismatch_log,
        )


@dataclass(frozen=True)
class OutcomeStep(PipelineStep):
    label: str
    runner: Callable[[], ActionOutcome]
    success_log: str
    success_detail: Optional[str]
    mismatch_log: Optional[str]

    def execute(self, state: PipelineState) -> Optional[ActionOutcome]:
        return state.plan.run_outcome(
            self.label,
            self.runner,
            success_log=self.success_log,
            success_detail=self.success_detail,
            mismatch_log=self.mismatch_log,
        )


@dataclass(frozen=True)
class VerifyStep(PipelineStep):
    success_log: str
    success_detail: Optional[str]

    def execute(self, state: PipelineState) -> Optional[ActionOutcome]:
        return state.plan.verify_eventual(
            self.success_log,
            success_detail=self.success_detail,
        )


class TogglePipeline:
    """Composable pipeline used to enforce security toggles."""

    def __init__(self, plan: TogglePlan) -> None:
        self._plan = plan
        self._steps: list[PipelineStep] = []
        self._state = PipelineState(plan)

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
    ) -> "TogglePipeline":
        self._steps.append(
            CommandStep(
                label,
                runner,
                success_log,
                success_detail,
                mismatch_log,
                failure_log,
                attempts,
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
    ) -> "TogglePipeline":
        self._steps.append(
            BooleanStep(
                label,
                runner,
                success_log,
                success_detail,
                mismatch_log,
            )
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
    ) -> "TogglePipeline":
        self._steps.append(
            OutcomeStep(
                label,
                runner,
                success_log,
                success_detail,
                mismatch_log,
            )
        )
        return self

    def add_verification(
        self,
        success_log: str,
        *,
        success_detail: Optional[str] = None,
    ) -> "TogglePipeline":
        self._steps.append(VerifyStep(success_log, success_detail))
        return self

    def execute(self) -> Optional[ActionOutcome]:
        self._state.reset()
        for step in self._steps:
            outcome = step.execute(self._state)
            if outcome:
                return outcome
        return None

    @property
    def plan(self) -> TogglePlan:
        return self._plan

    @property
    def ctx(self) -> OutcomeBuilder:
        return self._plan.ctx

    @property
    def last_run(self) -> Optional[RunResult]:
        return self._state.last_run


def run_command(cmd: list[str], timeout: int = 30) -> RunResult:
    """Run a command with no visible window. Returns stdout, stderr, code."""

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=platform_state.CREATE_NO_WINDOW,
        text=True,
        encoding="utf-8",
    ) as proc:
        out, err = proc.communicate(timeout=timeout)
    return RunResult(proc.returncode, out.strip(), err.strip())


def dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys([it for it in items if it]))


def guarded_call(func: Callable[[], T], fallback: T) -> T:
    """Execute *func* and fall back gracefully on unexpected errors."""

    try:
        return func()
    except Exception as exc:  # pragma: no cover - defensive logging only
        _report_exception(exc)
        return fallback


def wait_for_state(
    probe: Callable[[], Optional[bool]],
    expected: bool,
    *,
    attempts: int = 6,
    base_delay: float = 0.35,
) -> bool:
    """Poll *probe* until it returns the expected boolean value."""

    for attempt in range(attempts):
        state = guarded_call(probe, None)
        if state is None:
            time.sleep(base_delay * (attempt + 1))
            continue
        if (state is True) if expected else (state is False):
            return True
        time.sleep(base_delay * (attempt + 1))
    return False


def wait_for_service_state(
    probe: Callable[[], Optional[str]],
    expected: str,
    *,
    attempts: int = 6,
    base_delay: float = 0.35,
) -> bool:
    """Poll *probe* until the service reaches *expected* state."""

    expected_upper = expected.upper()
    for attempt in range(attempts):
        state = guarded_call(probe, None)
        if state and state.upper() == expected_upper:
            return True
        time.sleep(base_delay * (attempt + 1))
    return False


def run_command_background(cmd: list[str], **popen_kwargs: Any) -> tuple[bool, Optional[subprocess.Popen]]:
    """Launch *cmd* in background. Returns (success, Popen)."""

    try:
        process = subprocess.Popen(cmd, **popen_kwargs)
        return True, process
    except Exception as exc:  # pragma: no cover - popen failure
        _report_exception(exc)
        return False, None


def run_powershell(ps_script: str, timeout: int = 30) -> RunResult:
    """Run a PowerShell one-liner invisibly with hardened flags."""

    if not platform_state.IS_WINDOWS or platform_state.POWERSHELL_EXE is None:
        return RunResult(1, "", "Windows-only")
    cmd = [
        platform_state.POWERSHELL_EXE,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        ps_script,
    ]
    return run_command(cmd, timeout=timeout)


def build_toggle_plan(
    feature: str,
    *,
    platform_detail: str,
    admin_message: str,
    probe: Callable[[], Optional[bool]],
    expected: bool,
) -> tuple[Optional[TogglePlan], Optional[ActionOutcome]]:
    """Construct a :class:`TogglePlan` gated by platform and privileges."""

    action = FeatureAction(
        feature,
        platform_detail=platform_detail,
        admin_message=admin_message,
    )
    if action.blocked:
        return None, action.blocked
    plan = TogglePlan(action.ctx, probe, expected)
    return plan, None


def drive_service_state(
    ctx: OutcomeBuilder,
    *,
    label: str,
    runner: Callable[[], bool],
    probe: Callable[[], Optional[str]],
    expected: str,
    success_log: str,
    mismatch_log: str,
    blocker_label: str,
) -> bool:
    """Drive a Windows service to ``expected`` state with verification."""

    if not platform_state.IS_WINDOWS:
        return False
    success = runner()
    ctx.log.add(label, "ok" if success else "failed")
    if not success:
        ctx.add_blockers(blocker_label)
        return False
    if wait_for_service_state(probe, expected):
        ctx.log.add("verification", success_log)
        return True
    ctx.log.add(label, mismatch_log)
    ctx.add_blockers(blocker_label)
    return False


__all__ = [
    "ActionOutcome",
    "ActionLog",
    "CommandStep",
    "DefenderStatus",
    "FeatureAction",
    "OutcomeBuilder",
    "PipelineState",
    "PipelineStep",
    "RunResult",
    "SecuritySnapshot",
    "TogglePipeline",
    "TogglePlan",
    "BooleanStep",
    "OutcomeStep",
    "VerifyStep",
    "build_toggle_plan",
    "dedupe",
    "drive_service_state",
    "guarded_call",
    "run_command",
    "run_command_background",
    "run_powershell",
    "wait_for_service_state",
    "wait_for_state",
]


def _report_exception(exc: BaseException) -> None:
    """Defer importing :mod:`coolbox.app` until necessary to avoid circular imports."""

    from coolbox.app import error_handler as eh  # local import to break circular dependency

    eh.handle_exception(type(exc), exc, exc.__traceback__)

