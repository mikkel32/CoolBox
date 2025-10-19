from __future__ import annotations

from types import SimpleNamespace
from typing import Sequence

from coolbox.utils.security.defender import (
    DefenderStatus as DefenderStatus,
    ensure_admin as ensure_admin,
    get_defender_status as get_defender_status,
    is_defender_enabled as is_defender_enabled,
    is_defender_supported as is_defender_supported,
    set_defender_enabled as set_defender_enabled,
    _ps as _ps,
    _run_ex as _run_ex,
)

platform: SimpleNamespace

__all__: Sequence[str]
