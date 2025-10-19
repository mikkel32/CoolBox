from __future__ import annotations

from typing import Optional, Sequence, Tuple


class DefenderStatus:
    realtime: bool | None
    services_ok: bool
    cmdlets_available: bool
    tamper_on: bool | None
    policy_lock: bool
    third_party_av_present: bool
    error: str | None


def ensure_admin() -> bool: ...


def is_defender_supported() -> bool: ...


def get_defender_status() -> DefenderStatus: ...


def is_defender_enabled() -> bool | None: ...


def set_defender_enabled(enabled: bool) -> Tuple[bool, Optional[str]]: ...


def _ps(script: str, *, timeout: float = ...) -> Tuple[str, int]: ...


def _run_ex(cmd: Sequence[str], timeout: float = ...) -> Tuple[str, int]: ...
