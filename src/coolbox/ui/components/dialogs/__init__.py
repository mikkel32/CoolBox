"""Dialog widgets for alerts and error handling."""
from __future__ import annotations

try:  # pragma: no cover - optional GUI dependency
    from .modern_error_dialog import ModernErrorDialog
except Exception:  # pragma: no cover - missing runtime deps
    ModernErrorDialog = None  # type: ignore[assignment]

__all__ = ["ModernErrorDialog"]
