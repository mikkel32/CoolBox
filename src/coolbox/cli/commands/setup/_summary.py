"""Run summary helpers for the setup command."""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from typing import Sequence

from coolbox.setup.run_summary import CommandRecord, RunSummaryPanelModel

from ._logging import log
from ._ui import Panel, console, box

__all__ = ["RunSummary", "SUMMARY", "send_telemetry"]


class RunSummary(RunSummaryPanelModel):
    """Rich-enabled summary that logs command diagnostics."""

    def __init__(self) -> None:
        super().__init__()
        self._logger = logging.getLogger("coolbox.setup.summary")

    def add_warning(self, message: str) -> None:  # type: ignore[override]
        super().add_warning(message)
        log(f"[yellow]WARN[/]: {message}")

    def add_error(self, message: str) -> None:  # type: ignore[override]
        super().add_error(message)
        log(f"[red]ERROR[/]: {message}")

    def begin_command(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
    ) -> CommandRecord:  # type: ignore[override]
        record = super().begin_command(command, cwd=cwd)
        self._logger.debug("Executing command: %s", " ".join(map(str, command)))
        return record

    def render(self) -> None:
        panel = self.as_panel()
        if hasattr(console, "print"):
            console.print(panel)
        else:  # pragma: no cover - fallback console
            print(panel)


SUMMARY = RunSummary()


def send_telemetry(summary: RunSummary) -> None:
    url = os.environ.get("COOLBOX_TELEMETRY_URL")
    if not url:
        return
    data = {
        "warnings": summary.warnings,
        "errors": summary.errors,
        "platform": sys.platform,
        "commands": [
            {
                "command": " ".join(map(str, record.command)),
                "exit_code": record.exit_code,
                "duration": record.duration,
                "hint": record.hint,
            }
            for record in summary.commands
        ],
    }
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=2)
    except Exception:
        pass
