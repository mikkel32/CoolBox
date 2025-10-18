from __future__ import annotations

"""Reusable test plugins for exercising the supervisor pipeline."""

import time
from typing import Sequence

from coolbox.setup.orchestrator import SetupStage
from coolbox.setup.plugins import SetupPlugin


class SlowPlugin(SetupPlugin):
    """Plugin that intentionally idles during lifecycle callbacks."""

    name = "fixtures.slow"

    def __init__(self, *, delay: float = 0.25) -> None:
        self.delay = delay

    def register(self, registrar) -> None:  # type: ignore[override]
        return None

    def before_stage(self, stage: SetupStage, context) -> None:  # type: ignore[override]
        time.sleep(self.delay)

    def after_stage(self, stage: SetupStage, results: Sequence, context) -> None:  # type: ignore[override]
        time.sleep(self.delay / 4)

    def before_task(self, task, context) -> None:  # type: ignore[override]
        time.sleep(self.delay / 10)

    def after_task(self, result, context) -> None:  # type: ignore[override]
        time.sleep(self.delay / 10)

    def on_error(self, task, error, context) -> None:  # type: ignore[override]
        time.sleep(self.delay / 10)


class CrashPlugin(SetupPlugin):
    """Plugin that raises immediately during ``before_stage``."""

    name = "fixtures.crash"

    def register(self, registrar) -> None:  # type: ignore[override]
        return None

    def before_stage(self, stage: SetupStage, context) -> None:  # type: ignore[override]
        raise RuntimeError("crash-triggered")

    def after_stage(self, stage: SetupStage, results: Sequence, context) -> None:  # type: ignore[override]
        return None

    def before_task(self, task, context) -> None:  # type: ignore[override]
        return None

    def after_task(self, result, context) -> None:  # type: ignore[override]
        return None

    def on_error(self, task, error, context) -> None:  # type: ignore[override]
        return None


__all__ = ["SlowPlugin", "CrashPlugin"]
