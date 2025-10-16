"""Run summary panel models and command logging for CoolBox setup."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence
import time

try:  # pragma: no cover - optional rich support
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover - fallback when rich unavailable
    Panel = Table = Text = None  # type: ignore


@dataclass
class CommandRecord:
    """Diagnostic information about a subprocess invocation."""

    command: Sequence[str]
    cwd: str | None = None
    duration: float = 0.0
    exit_code: int | None = None
    stderr: str | None = None
    hint: str | None = None
    started_at: float = field(default_factory=time.perf_counter)

    def finalize(
        self,
        *,
        exit_code: int | None,
        stderr: str | None,
        duration: float,
        hint: str | None,
    ) -> None:
        self.exit_code = exit_code
        self.stderr = (stderr or "").strip() or None
        self.duration = duration
        self.hint = hint

    @property
    def command_str(self) -> str:
        return " ".join(map(str, self.command))

    def status_badge(self) -> str:
        if self.exit_code in (0, None):
            return "[green]OK[/]"
        return f"[red]exit {self.exit_code}[/]"

    def duration_text(self) -> str:
        return f"{self.duration:.2f}s"


@dataclass
class RunSummaryPanelModel:
    """Aggregate diagnostic state rendered at the end of setup runs."""

    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    commands: List[CommandRecord] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def begin_command(self, command: Sequence[str], *, cwd: str | None = None) -> CommandRecord:
        record = CommandRecord(tuple(command), cwd=cwd)
        self.commands.append(record)
        return record

    def extend(self, other: "RunSummaryPanelModel") -> None:
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        self.commands.extend(other.commands)

    def as_panel(self) -> Panel | str:
        if Panel is None or Table is None:
            lines: List[str] = []
            if self.warnings:
                lines.append("Warnings:")
                lines.extend(f" - {w}" for w in self.warnings)
            if self.errors:
                lines.append("Errors:")
                lines.extend(f" - {e}" for e in self.errors)
            if self.commands:
                lines.append("Commands:")
                for record in self.commands:
                    lines.append(
                        f" - {record.command_str} ({record.duration_text()}, status={record.exit_code})"
                    )
                    if record.hint:
                        lines.append(f"   hint: {record.hint}")
                    if record.stderr:
                        lines.append(f"   stderr: {record.stderr}")
            return "\n".join(lines) or "No diagnostics recorded."

        table = Table(box=None)
        table.add_column("Command", overflow="fold")
        table.add_column("Status", no_wrap=True)
        table.add_column("Duration", no_wrap=True)
        if self.commands:
            for record in self.commands:
                table.add_row(record.command_str, record.status_badge(), record.duration_text())
        else:
            table.add_row("(no commands recorded)", "", "")

        details = Table.grid(padding=(0, 1))
        if self.warnings:
            warn_text = Text("\n".join(self.warnings), style="yellow")
            details.add_row("Warnings", warn_text)
        if self.errors:
            err_text = Text("\n".join(self.errors), style="red")
            details.add_row("Errors", err_text)
        if any(record.hint for record in self.commands):
            hints = [record.hint for record in self.commands if record.hint]
            hints_text = Text("\n".join(hints), style="cyan")
            details.add_row("Hints", hints_text)

        if details.row_count:
            return Panel.fit(details, title="Run Summary", border_style="magenta")
        return Panel.fit(table, title="Run Summary", border_style="magenta")

    def latest_error(self) -> str | None:
        return self.errors[-1] if self.errors else None

    def latest_warning(self) -> str | None:
        return self.warnings[-1] if self.warnings else None

    def last_command(self) -> CommandRecord | None:
        return self.commands[-1] if self.commands else None


__all__ = ["CommandRecord", "RunSummaryPanelModel"]
