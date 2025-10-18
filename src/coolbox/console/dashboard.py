"""Textual-powered dashboard for the setup orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
import time
from types import SimpleNamespace
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    TYPE_CHECKING,
    cast,
)

try:  # pragma: no cover - optional rich dependency
    from rich.markup import escape as _rich_escape
except Exception:  # pragma: no cover - executed when rich missing
    def _escape_markup(value: str) -> str:
        return value
else:  # pragma: no cover - exercised indirectly in UI tests
    def _escape_markup(value: str) -> str:
        return _rich_escape(value)

from .events import (
    DashboardEvent,
    DashboardEventType,
    LogEvent,
    StageEvent,
    TaskEvent,
    ThemeEvent,
    TroubleshootingEvent,
)
from coolbox.telemetry import TelemetryKnowledgeBase

TEXTUAL_AVAILABLE: bool = False

if TYPE_CHECKING:  # pragma: no cover - typing only
    from textual import events
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.message import Message
    from textual.reactive import reactive
    from textual.widgets import DataTable, Footer, Header, Input, Static
    from textual.widgets._log import Log  # type: ignore[attr-defined]
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.console import Group, RenderableType
    from coolbox.setup.orchestrator import SetupOrchestrator, SetupStage
else:  # pragma: no cover - runtime import guard
    try:
        from textual import events
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Container, Horizontal, Vertical
        from textual.message import Message
        from textual.reactive import reactive
        from textual.widgets import DataTable, Footer, Header, Input, Static
        from textual.widgets._log import Log  # type: ignore[attr-defined]
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        from rich.console import Group, RenderableType

        TEXTUAL_AVAILABLE = True
    except Exception:  # pragma: no cover - fallback when textual missing
        TEXTUAL_AVAILABLE = False

        RenderableType = Any  # type: ignore[assignment]

        class _StubStyles(SimpleNamespace):
            def __init__(self) -> None:
                super().__init__(background=None, color=None)

        class _StubWidget:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.styles = _StubStyles()

            def update(self, *args: Any, **kwargs: Any) -> None:
                return None

            def refresh(self) -> None:
                return None

        class _StubApp(_StubWidget):
            def run(self, *args: Any, **kwargs: Any) -> None:
                return None

            def exit(self) -> None:
                return None

            def post_message(self, *args: Any, **kwargs: Any) -> None:
                return None

            def set_theme(self, *args: Any, **kwargs: Any) -> None:
                return None

        class _StubMessage:
            pass

        class _StubInput(_StubWidget):
            class Submitted:
                def __init__(self, value: str, input: _StubInput) -> None:  # type: ignore[name-defined]
                    self.value = value
                    self.input = input

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self.value = ""
                self.display = True

            def focus(self) -> None:
                return None

        class _StubDataTable(_StubWidget):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self.columns: list[Any] = []

            def add_column(self, _name: str) -> None:
                self.columns.append(_name)

            def add_row(self, *args: Any, **kwargs: Any) -> None:
                return None

            def clear(self) -> None:
                return None

        class _StubLog(_StubWidget):
            def write(self, *args: Any, **kwargs: Any) -> None:
                return None

        class _StubBinding:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

        class _StubContainer(_StubWidget):
            def __init__(self, *children: Any, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.children = children

        class _StubHorizontal(_StubContainer):
            pass

        class _StubVertical(_StubContainer):
            pass

        def reactive(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
            return args[0] if args else None

        events = SimpleNamespace()  # type: ignore[assignment]
        App = _StubApp  # type: ignore[assignment]
        ComposeResult = Iterable[Any]  # type: ignore[assignment]
        Binding = _StubBinding  # type: ignore[assignment]
        Container = _StubContainer  # type: ignore[assignment]
        Horizontal = _StubHorizontal  # type: ignore[assignment]
        Vertical = _StubVertical  # type: ignore[assignment]
        Message = _StubMessage  # type: ignore[assignment]
        Static = Header = Footer = _StubWidget  # type: ignore[assignment]
        Input = _StubInput  # type: ignore[assignment]
        DataTable = _StubDataTable  # type: ignore[assignment]
        Log = _StubLog  # type: ignore[assignment]
        Panel = Table = Text = Group = _StubWidget  # type: ignore[assignment]

if TYPE_CHECKING:
    TEXTUAL_AVAILABLE = True


class DashboardLayout(str, Enum):
    """Predefined layout choices for the Textual dashboard."""

    MINIMAL = "minimal"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class DashboardTheme(str, Enum):
    """Selectable theme identifiers."""

    MINIMAL = "minimal"
    HIGH_CONTRAST = "high-contrast"
    BRANDED = "branded"


@dataclass(frozen=True)
class DashboardThemeProfile:
    """Visual palette applied to dashboard widgets."""

    name: DashboardTheme
    background: str
    accent: str
    success: str
    error: str
    warning: str
    text: str


@dataclass
class DashboardThemeSettings:
    """Theme metadata used by renderers."""

    profile: DashboardThemeProfile
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.name.value,
            "background": self.profile.background,
            "accent": self.profile.accent,
            "success": self.profile.success,
            "error": self.profile.error,
            "warning": self.profile.warning,
            "text": self.profile.text,
            "overrides": dict(self.overrides),
        }


THEME_PROFILES: dict[DashboardTheme, DashboardThemeProfile] = {
    DashboardTheme.MINIMAL: DashboardThemeProfile(
        name=DashboardTheme.MINIMAL,
        background="#101218",
        accent="#3d6af2",
        success="#44c775",
        error="#ff5f56",
        warning="#f7c948",
        text="#e3e9ff",
    ),
    DashboardTheme.HIGH_CONTRAST: DashboardThemeProfile(
        name=DashboardTheme.HIGH_CONTRAST,
        background="#000000",
        accent="#f0f000",
        success="#00ff00",
        error="#ff0000",
        warning="#ffaa00",
        text="#ffffff",
    ),
    DashboardTheme.BRANDED: DashboardThemeProfile(
        name=DashboardTheme.BRANDED,
        background="#0b1a2a",
        accent="#ff3cac",
        success="#2cf6b3",
        error="#ff5c8a",
        warning="#ffc15e",
        text="#f7f9fd",
    ),
}


class BaseDashboard:
    """Interface for dashboard renderers."""

    def start(self) -> None:  # pragma: no cover - interface hook
        """Start rendering the dashboard."""

    def stop(self) -> None:  # pragma: no cover - interface hook
        """Stop rendering the dashboard."""

    def handle_event(self, event: DashboardEvent) -> None:
        raise NotImplementedError

    def apply_theme(self, theme: DashboardThemeSettings) -> None:
        raise NotImplementedError

    def export_state(self) -> Mapping[str, Any]:
        raise NotImplementedError


class JsonDashboard(BaseDashboard):
    """Headless dashboard implementation that records events in JSON."""

    def __init__(
        self,
        *,
        theme: DashboardTheme = DashboardTheme.MINIMAL,
        knowledge_base: TelemetryKnowledgeBase | None = None,
    ) -> None:
        self.theme = DashboardThemeSettings(THEME_PROFILES[theme])
        self.events: list[dict[str, Any]] = []
        self._knowledge_base = knowledge_base or TelemetryKnowledgeBase()

    def handle_event(self, event: DashboardEvent) -> None:
        self.events.append(event.as_dict())
        if isinstance(event, TaskEvent) and event.status == "failed":
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            failure_code = payload.get("failure_code")
            error_type = payload.get("error_type")
            stage_name = payload.get("stage")
            if not isinstance(stage_name, str) or not stage_name:
                stage_name = event.stage.value if hasattr(event.stage, "value") else str(event.stage)
            suggestion = self._knowledge_base.suggest_fix(
                failure_code=failure_code,
                error_type=error_type,
                stage=stage_name,
                task=event.task,
            )
            if suggestion:
                suggestion_payload = suggestion.to_payload()
                self.events.append(
                    {
                        "type": "suggestion",
                        "task": event.task,
                        "stage": event.stage.value if hasattr(event.stage, "value") else str(event.stage),
                        "suggestion": suggestion.title,
                        "summary": suggestion.describe(),
                        "details": suggestion_payload,
                        "confidence": suggestion.confidence,
                        "failure_code": failure_code,
                        "stage": stage_name,
                    }
                )

    def apply_theme(self, theme: DashboardThemeSettings) -> None:
        self.theme = theme
        self.events.append(ThemeEvent(theme.profile.name.value).as_dict())

    def export_state(self) -> Mapping[str, Any]:
        return {
            "theme": self.theme.to_dict(),
            "events": list(self.events),
            "knowledge_base": self._knowledge_base.summarize(),
        }

    def start(self) -> None:  # pragma: no cover - nothing to do
        self.events.append({"type": "lifecycle", "payload": {"status": "started"}})

    def stop(self) -> None:  # pragma: no cover - nothing to do
        self.events.append({"type": "lifecycle", "payload": {"status": "stopped"}})

    def as_json(self) -> str:
        return json.dumps(self.export_state(), indent=2)


@dataclass
class DiagnosticResult:
    name: str
    started_at: float
    finished_at: float
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "payload": dict(self.payload),
        }


class TroubleshootingStudio:
    """Executes diagnostics and prepares sanitized bundles."""

    def __init__(
        self,
        *,
        diagnostics: Optional[Mapping[str, Callable[[], Mapping[str, Any]]]] = None,
        sanitizer: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        publisher: Optional[Callable[[DashboardEvent], None]] = None,
    ) -> None:
        self._diagnostics: Dict[str, Callable[[], Mapping[str, Any]]] = dict(diagnostics or {})
        self._publisher = publisher
        self._sanitizer = sanitizer or self._default_sanitizer
        if not self._diagnostics:
            self._install_default_diagnostics()

    def _default_sanitizer(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        sanitized: Dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                sanitized[key] = value
            else:
                sanitized[key] = "<redacted>"
        return sanitized

    def _install_default_diagnostics(self) -> None:
        self._diagnostics.update(
            {
                "doctor": self._doctor_check,
                "virtualenv": self._virtualenv_integrity,
                "collect": self._problem_collection,
            }
        )

    def register(self, name: str, callback: Callable[[], Mapping[str, Any]]) -> None:
        self._diagnostics[name] = callback

    def run(self, name: str) -> DiagnosticResult:
        if name not in self._diagnostics:
            raise KeyError(f"Unknown diagnostic '{name}'")
        started = time.time()
        payload = self._diagnostics[name]()
        sanitized = self._sanitizer(payload)
        finished = time.time()
        result = DiagnosticResult(name=name, started_at=started, finished_at=finished, payload=sanitized)
        if self._publisher:
            self._publisher(TroubleshootingEvent(name, sanitized))
        return result

    def available(self) -> Iterable[str]:
        return sorted(self._diagnostics)

    def export_bundle(self, destination: Path) -> Path:
        """Write a sanitized diagnostics bundle to *destination*."""

        bundle: Dict[str, Any] = {}
        for name in self.available():
            result = self.run(name)
            bundle[name] = result.as_dict()
        destination.write_text(json.dumps(bundle, indent=2))
        return destination

    # --- built-in diagnostics -------------------------------------------------
    def _doctor_check(self) -> Mapping[str, Any]:
        import platform
        import sys

        return {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
        }

    def _virtualenv_integrity(self) -> Mapping[str, Any]:
        import sys

        base_prefix = getattr(sys, "base_prefix", sys.prefix)
        return {
            "prefix": sys.prefix,
            "base_prefix": base_prefix,
            "is_venv": sys.prefix != base_prefix,
        }

    def _problem_collection(self) -> Mapping[str, Any]:
        return {
            "log_files": [],
            "warnings": [],
            "notes": "No problems detected",
        }


if TEXTUAL_AVAILABLE:

    class DashboardEventMessage(Message):
        """Message posted when orchestrator events arrive."""

        def __init__(self, event: DashboardEvent) -> None:
            super().__init__()
            self.event = event

    class SummaryTiles(Static):
        """Display stage summaries using themed badges and timing."""

        stages: reactive[dict[str, str]] = reactive(dict)
        _STATUS_MAP: Dict[str, tuple[str, str, str]] = {
            "pending": ("⏳", "Pending", "dim"),
            "in-progress": ("▶", "In Progress", "cyan"),
            "completed": ("✔", "Completed", "green"),
            "failed": ("✖", "Failed", "red"),
            "skipped": ("⤴", "Skipped", "yellow"),
        }

        def __init__(self) -> None:
            super().__init__("")
            self.stages = {}
            self._order: list[str] = []
            self._started: Dict[str, float] = {}
            self._durations: Dict[str, float] = {}
            self._theme: DashboardThemeProfile = THEME_PROFILES[DashboardTheme.MINIMAL]
            self._plain_summary = ""
            self._current_renderable: RenderableType | None = None

        def set_theme(self, profile: DashboardThemeProfile) -> None:
            self._theme = profile
            self.update(self._render_tiles())

        def update_stage(self, stage: str, status: str) -> None:
            normalized = self._normalize_status(status)
            now = time.perf_counter()
            if stage not in self._order:
                self._order.append(stage)
            if normalized == "in-progress":
                self._started[stage] = now
            elif normalized in {"completed", "failed", "skipped"}:
                started = self._started.pop(stage, None)
                if started is not None:
                    self._durations[stage] = now - started
            self.stages = {**self.stages, stage: normalized}
            self.update(self._render_tiles())

        def _normalize_status(self, status: str) -> str:
            value = (status or "").lower()
            if value in {"started", "running", "progress"}:
                return "in-progress"
            if value in self._STATUS_MAP:
                return value
            return "pending"

        def _render_tiles(self) -> Panel:
            table = Table.grid(padding=(0, 1))
            table.add_column("Stage", ratio=1)
            table.add_column("Status", justify="right")
            if not self._order:
                table.add_row(Text("Waiting for stages…", style="dim italic"), Text(""))
            plain_lines: list[str] = []
            for stage in self._order:
                status = self.stages.get(stage, "pending")
                icon, label, style = self._STATUS_MAP.get(status, self._STATUS_MAP["pending"])
                stage_title = self._format_stage_name(stage)
                stage_text = Text(stage_title, style="bold")
                if stage.lower() != stage_title.lower():
                    stage_text.append(f" [dim]({stage})[/]")
                status_text = Text(f"{icon} {label}", style=style)
                duration = self._durations.get(stage)
                if duration is not None and duration > 0:
                    status_text.append(f" · {duration:.1f}s", style="dim")
                table.add_row(stage_text, status_text)
                plain_lines.append(f"{stage}: {status}")
            subtitle = "Ctrl+P · Rerun stage"
            panel = Panel(
                table,
                title="Setup Progress",
                border_style=self._theme.accent,
                padding=(0, 1),
                subtitle=subtitle,
                subtitle_align="right",
            )
            self._plain_summary = "\n".join(plain_lines) if plain_lines else ""
            self._current_renderable = panel
            return panel

        def _format_stage_name(self, stage: str) -> str:
            cleaned = stage.replace("_", " ").replace("-", " ")
            return " ".join(word.capitalize() for word in cleaned.split())

        class _RenderableProxy:
            def __init__(self, renderable: RenderableType, plain: str) -> None:
                self._renderable = renderable
                self._plain = plain

            def __rich_console__(self, console: Any, options: Any) -> Iterable[Any]:
                yield from console.render(self._renderable, options)

            def __str__(self) -> str:
                return self._plain or str(self._renderable)

        def render(self) -> RenderableType:
            renderable = self._current_renderable or self._render_tiles()
            return self._RenderableProxy(renderable, self._plain_summary)

    class DependencyGraph(DataTable):
        """Tabular representation of task dependencies."""

        def __init__(self) -> None:
            super().__init__(zebra_stripes=True)
            self._rows: Dict[str, list[str]] = {}
            self._theme: DashboardThemeProfile = THEME_PROFILES[DashboardTheme.MINIMAL]

        def on_mount(self) -> None:
            if not self.columns:
                self.add_column("Task")
                self.add_column("Depends On")

        def record(self, task: str, deps: Iterable[str]) -> None:
            deps_list = list(deps)
            self._rows[task] = deps_list
            self._refresh()

        def _refresh(self) -> None:
            self.clear()
            for task, deps in sorted(self._rows.items()):
                task_style = self._theme.accent if not deps else self._theme.text
                deps_text = ", ".join(deps) if deps else "<none>"
                self.add_row(f"[{task_style}]{task}[/]", deps_text)

        def set_theme(self, profile: DashboardThemeProfile) -> None:
            self._theme = profile
            self.styles.background = profile.background
            self.styles.color = profile.text
            self._refresh()

    class LiveLog(Log):
        """Log panel that highlights levels."""

        def __init__(self) -> None:
            super().__init__()
            self._theme: DashboardThemeProfile = THEME_PROFILES[DashboardTheme.MINIMAL]

        def set_theme(self, profile: DashboardThemeProfile) -> None:
            self._theme = profile
            self.styles.background = profile.background
            self.styles.color = profile.text

        def add_entry(self, level: str, message: str, *, theme: DashboardThemeProfile) -> None:
            timestamp = time.strftime("%H:%M:%S")
            severity = level.lower()
            color = {
                "info": theme.accent,
                "debug": theme.text,
                "warning": theme.warning,
                "error": theme.error,
            }.get(severity, theme.text)
            icon = {"info": "ℹ", "debug": "·", "warning": "⚠", "error": "✖"}.get(severity, "•")
            safe_message = _escape_markup(message)
            self.write(
                f"[dim]{timestamp}[/] "
                f"[{color}]{icon} {severity.upper():>7}[/] "
                f"{safe_message}"
            )

    class CommandPalette(Container):
        """Simple command palette that reruns stages by name."""

        def __init__(self, orchestrator: "SetupOrchestrator") -> None:
            super().__init__(id="command-palette")
            self._orchestrator = orchestrator
            self._theme: DashboardThemeProfile = THEME_PROFILES[DashboardTheme.MINIMAL]
            self._help = Static("", classes="palette-help")
            self._help_text = ""
            self._input = Input()
            cast(Any, self._input).placeholder = "Enter stage id (press Enter)"
            cast(Any, self._input).display = False
            cast(Any, self._help).display = False

        def compose(self) -> ComposeResult:
            yield self._help
            yield self._input

        def toggle(self) -> None:
            display = not cast(Any, self._input).display
            cast(Any, self._input).display = display
            cast(Any, self._help).display = display
            if display:
                stages = getattr(self._orchestrator, "stage_order", [])
                if stages:
                    stage_list = ", ".join(stage.value for stage in stages)
                    self._help_text = (
                        f"[{self._theme.accent}]Available stages[/]: [dim]{stage_list}[/]"
                    )
                else:
                    self._help_text = ""
                if self._help_text:
                    self._help.update(self._help_text)
                cast(Any, self._input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            from coolbox.setup.orchestrator import SetupStage  # local import

            if event.input is not self._input:
                return
            value = event.value.strip()
            if value:
                stage = None
                try:
                    stage = SetupStage(value)
                except Exception:
                    for candidate in getattr(self._orchestrator, "stage_order", []):
                        if candidate.value.startswith(value):
                            stage = candidate
                            break
                if stage is not None:
                    self._orchestrator.rerun_stage(stage)
            cast(Any, self._input).value = ""
            cast(Any, self._input).display = False
            cast(Any, self._help).display = False
            event.stop()

        def set_theme(self, profile: DashboardThemeProfile) -> None:
            self._theme = profile
            self.styles.background = profile.background
            self.styles.color = profile.text
            self._help.styles.color = profile.accent
            if self._help_text:
                self._help.update(self._help_text)

    class TroubleshootingPanel(Static):
        """Textual wrapper for the troubleshooting studio."""

        def __init__(self, studio: TroubleshootingStudio) -> None:
            super().__init__("Diagnostics not run")
            self._studio = studio

        def run_all(self) -> None:
            lines: list[str] = []
            for name in self._studio.available():
                result = self._studio.run(name)
                lines.append(f"[b]{name}[/b]\n{json.dumps(result.payload, indent=2)}")
            self.update("\n\n".join(lines))

        def set_theme(self, profile: DashboardThemeProfile) -> None:
            self.styles.background = profile.background
            self.styles.color = profile.text

    class TextualDashboardApp(App):
        """Textual application wrapping dashboard widgets."""

        CSS = """
        Screen { background: $background; color: $text; }
        #main { height: 1fr; padding: 1 2; }
        SummaryTiles { border: tall $accent; padding: 1 2; }
        DataTable { border: round $accent; padding: 0 1; }
        Log { border: round $accent; padding: 0 1; }
        #command-palette { border: double $accent; padding: 1 2; }
        #command-palette .palette-help { color: $accent; }
        #troubleshooting { border: round $accent; padding: 1 2; }
        """
        BINDINGS = [
            Binding("ctrl+p", "toggle_palette", "Command Palette"),
            Binding("ctrl+d", "run_diagnostics", "Troubleshooting Studio"),
            Binding("ctrl+t", "cycle_theme", "Cycle Theme"),
        ]

        def __init__(
            self,
            orchestrator: "SetupOrchestrator",
            *,
            theme: DashboardThemeSettings,
            layout: DashboardLayout,
            studio: TroubleshootingStudio,
            knowledge_base: TelemetryKnowledgeBase,
        ) -> None:
            super().__init__()
            self._orchestrator = orchestrator
            self._theme = theme
            self._layout = layout
            self._studio = studio
            self._knowledge_base = knowledge_base
            self.summary = SummaryTiles()
            self.log_panel = LiveLog()
            self.deps = DependencyGraph()
            self.palette = CommandPalette(orchestrator)
            self.troubleshooting = TroubleshootingPanel(studio)
            self.summary.id = "summary"
            self.log_panel.id = "log"
            self.deps.id = "dependencies"
            self.troubleshooting.id = "troubleshooting"
            self._themes = list(THEME_PROFILES.values())
            self._theme_index = self._themes.index(theme.profile)
            self.summary.set_theme(theme.profile)
            self.deps.set_theme(theme.profile)
            self.log_panel.set_theme(theme.profile)
            self.palette.set_theme(theme.profile)
            self.troubleshooting.set_theme(theme.profile)

        def compose(self) -> ComposeResult:
            yield Header()
            body = self._build_layout()
            yield body
            yield self.palette
            yield self.troubleshooting
            yield Footer()

        def on_mount(self) -> None:
            self.set_theme(self._theme.profile)
            if hasattr(self._orchestrator, "stage_order"):
                for stage in self._orchestrator.stage_order:
                    self.summary.update_stage(stage.value, "pending")

        def _build_layout(self) -> Container | Horizontal | Vertical:
            if self._layout is DashboardLayout.HORIZONTAL:
                return Horizontal(self.summary, self.deps, self.log_panel, id="main")
            if self._layout is DashboardLayout.VERTICAL:
                return Vertical(self.summary, self.deps, self.log_panel, id="main")
            return Container(Vertical(self.summary, self.deps), self.log_panel, id="main")

        def action_toggle_palette(self) -> None:
            self.palette.toggle()

        def action_run_diagnostics(self) -> None:
            self.troubleshooting.run_all()

        def action_cycle_theme(self) -> None:
            self._theme_index = (self._theme_index + 1) % len(self._themes)
            self.set_theme(self._themes[self._theme_index])

        def set_theme(self, profile: DashboardThemeProfile) -> None:
            self._theme = DashboardThemeSettings(profile)
            self.styles.background = profile.background
            self.styles.color = profile.text
            self.summary.set_theme(profile)
            self.deps.set_theme(profile)
            self.log_panel.set_theme(profile)
            self.palette.set_theme(profile)
            self.troubleshooting.set_theme(profile)
            self.refresh()

        def handle_dashboard_event(self, event: DashboardEvent) -> None:
            if isinstance(event, StageEvent):
                self.summary.update_stage(event.stage.value, event.status)
                if event.status == "completed":
                    self.log_panel.add_entry("info", f"Stage {event.stage.value} completed", theme=self._theme.profile)
            elif isinstance(event, TaskEvent):
                deps = event.payload.get("dependencies", []) if isinstance(event.payload, Mapping) else []
                self.deps.record(event.task, deps)
                if event.status == "failed" and event.error:
                    self.log_panel.add_entry("error", event.error, theme=self._theme.profile)
                    payload = event.payload if isinstance(event.payload, Mapping) else {}
                    failure_code = payload.get("failure_code")
                    error_type = payload.get("error_type")
                    stage_name = payload.get("stage")
                    if not isinstance(stage_name, str) or not stage_name:
                        stage_name = event.stage.value if hasattr(event.stage, "value") else str(event.stage)
                    suggestion = self._knowledge_base.suggest_fix(
                        failure_code=failure_code,
                        error_type=error_type,
                        stage=stage_name,
                        task=event.task,
                    )
                    if suggestion:
                        self.log_panel.add_entry(
                            "info",
                            f"Suggested fix for {event.task}: {suggestion.describe()}",
                            theme=self._theme.profile,
                        )
            elif isinstance(event, LogEvent):
                self.log_panel.add_entry(event.level, event.message, theme=self._theme.profile)
            elif isinstance(event, TroubleshootingEvent):
                self.log_panel.add_entry("info", f"Diagnostic {event.diagnostic} complete", theme=self._theme.profile)
            elif isinstance(event, ThemeEvent):
                profile = THEMES.get(event.theme)
                if profile:
                    self.set_theme(profile)

        def on_dashboard_event_message(self, message: DashboardEventMessage) -> None:
            self.handle_dashboard_event(message.event)

    THEMES = {theme.value: profile for theme, profile in THEME_PROFILES.items()}


class TextualDashboard(BaseDashboard):
    """Textual dashboard wrapper that can receive orchestrator events."""

    def __init__(
        self,
        orchestrator: "SetupOrchestrator",
        *,
        layout: DashboardLayout = DashboardLayout.MINIMAL,
        theme: DashboardTheme = DashboardTheme.MINIMAL,
        studio: Optional[TroubleshootingStudio] = None,
        knowledge_base: TelemetryKnowledgeBase | None = None,
    ) -> None:
        if not TEXTUAL_AVAILABLE:  # pragma: no cover - runtime guard
            raise RuntimeError("textual is required for the interactive dashboard")
        self.orchestrator = orchestrator
        self.theme_settings = DashboardThemeSettings(THEME_PROFILES[theme])
        self.layout = layout
        self.studio = studio or TroubleshootingStudio(publisher=self._publish)
        self.knowledge = knowledge_base or TelemetryKnowledgeBase()
        self.app = TextualDashboardApp(
            orchestrator,
            theme=self.theme_settings,
            layout=layout,
            studio=self.studio,
            knowledge_base=self.knowledge,
        )
        self._running = False

    def _publish(self, event: DashboardEvent) -> None:
        if self._running:
            self.app.post_message(DashboardEventMessage(event))

    def start(self) -> None:
        self._running = True
        self.app.run(headless=True, inline=True)

    def stop(self) -> None:
        if self._running:
            self.app.exit()
        self._running = False

    def handle_event(self, event: DashboardEvent) -> None:
        if self._running:
            self.app.post_message(DashboardEventMessage(event))

    def apply_theme(self, theme: DashboardThemeSettings) -> None:
        self.theme_settings = theme
        if self._running:
            self.app.set_theme(theme.profile)

    def export_state(self) -> Mapping[str, Any]:
        return {
            "theme": self.theme_settings.to_dict(),
            "running": self._running,
            "knowledge_base": self.knowledge.summarize(),
        }


def create_dashboard(
    orchestrator: "SetupOrchestrator",
    *,
    mode: str = "textual",
    layout: DashboardLayout = DashboardLayout.MINIMAL,
    theme: DashboardTheme = DashboardTheme.MINIMAL,
    knowledge_base: TelemetryKnowledgeBase | None = None,
) -> BaseDashboard:
    """Factory returning a dashboard implementation."""

    if mode == "json":
        return JsonDashboard(theme=theme, knowledge_base=knowledge_base)
    return TextualDashboard(orchestrator, layout=layout, theme=theme, knowledge_base=knowledge_base)


__all__ = [
    "BaseDashboard",
    "DashboardLayout",
    "DashboardTheme",
    "DashboardThemeProfile",
    "DashboardThemeSettings",
    "JsonDashboard",
    "TextualDashboard",
    "TroubleshootingStudio",
    "create_dashboard",
]
