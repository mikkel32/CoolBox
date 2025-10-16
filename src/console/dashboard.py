"""Textual-powered dashboard for the setup orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional

from .events import (
    DashboardEvent,
    DashboardEventType,
    LogEvent,
    StageEvent,
    TaskEvent,
    ThemeEvent,
    TroubleshootingEvent,
)
from src.telemetry import TelemetryKnowledgeBase

try:  # pragma: no cover - optional dependency guard
    from textual import events
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.message import Message
    from textual.reactive import reactive
    from textual.widgets import DataTable, Footer, Header, Input, Static
    from textual.widgets._log import Log  # type: ignore[attr-defined]

    TEXTUAL_AVAILABLE = True
except Exception:  # pragma: no cover - fallback when textual missing
    TEXTUAL_AVAILABLE = False
    App = object  # type: ignore
    ComposeResult = Iterable  # type: ignore
    Binding = object  # type: ignore
    Container = Horizontal = Vertical = object  # type: ignore
    Message = object  # type: ignore
    events = object  # type: ignore
    Static = Input = Header = Footer = object  # type: ignore
    DataTable = object  # type: ignore
    Log = object  # type: ignore


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
            suggestion = self._knowledge_base.suggest_fix(
                failure_code=failure_code,
                error_type=error_type,
            )
            if suggestion:
                self.events.append(
                    {
                        "type": "suggestion",
                        "task": event.task,
                        "stage": event.stage.value if hasattr(event.stage, "value") else str(event.stage),
                        "suggestion": suggestion,
                        "failure_code": failure_code,
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
        """Display stage summaries in tiles."""

        stages: reactive[dict[str, str]] = reactive(dict)

        def __init__(self) -> None:
            super().__init__("")
            self.stages = {}

        def update_stage(self, stage: str, status: str) -> None:
            self.stages = {**self.stages, stage: status}
            lines = [f"[b]{stage}[/b]: {status}" for stage, status in self.stages.items()]
            self.update("\n".join(lines) or "No stages yet")

    class DependencyGraph(DataTable):
        """Tabular representation of task dependencies."""

        def __init__(self) -> None:
            super().__init__(zebra_stripes=True)
            self._rows: Dict[str, list[str]] = {}

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
                self.add_row(task, ", ".join(deps) if deps else "<none>")

    class LiveLog(Log):
        """Log panel that highlights levels."""

        def add_entry(self, level: str, message: str, *, theme: DashboardThemeProfile) -> None:
            color = {
                "info": theme.text,
                "debug": theme.text,
                "warning": theme.warning,
                "error": theme.error,
            }.get(level.lower(), theme.text)
            self.write(f"[{color}]{level.upper():>7}[/] {message}")

    class CommandPalette(Container):
        """Simple command palette that reruns stages by name."""

        def __init__(self, orchestrator: "SetupOrchestrator") -> None:
            super().__init__()
            self._orchestrator = orchestrator
            self._input = Input(placeholder="Enter stage id (tab to cancel)")
            self._input.display = False

        def compose(self) -> ComposeResult:
            yield self._input

        def toggle(self) -> None:
            self._input.display = not self._input.display
            if self._input.display:
                self._input.focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            from src.setup.orchestrator import SetupStage  # local import

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
            self._input.value = ""
            self._input.display = False
            event.stop()

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

    class TextualDashboardApp(App):
        """Textual application wrapping dashboard widgets."""

        CSS = """
        Screen { background: $background; color: $text; }
        #main { height: 1fr; }
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
            self._themes = list(THEME_PROFILES.values())
            self._theme_index = self._themes.index(theme.profile)

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

        def _build_layout(self) -> Container:
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
            self.log_panel.styles.background = profile.background
            self.summary.styles.background = profile.background
            self.deps.styles.background = profile.background
            self.troubleshooting.styles.background = profile.background
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
                    suggestion = self._knowledge_base.suggest_fix(
                        failure_code=failure_code,
                        error_type=error_type,
                    )
                    if suggestion:
                        self.log_panel.add_entry(
                            "info",
                            f"Suggested fix for {event.task}: {suggestion}",
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
