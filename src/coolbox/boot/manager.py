"""Boot manager responsible for orchestrating the CoolBox startup pipeline."""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence

from importlib.resources.abc import Traversable

from jsonschema import Draft7Validator, ValidationError

try:  # pragma: no cover - optional dependency
    import yaml
except Exception:  # pragma: no cover - fall back to JSON parsing only
    yaml = None

from coolbox.console import DashboardLayout, DashboardTheme, LogEvent, create_dashboard
from coolbox.plugins import (
    BootManifest,
    BootProfile as ManifestBootProfile,
    ManifestError as PluginManifestError,
    ManifestValidationError,
    PluginDefinition,
    ProfileDevSettings,
    load_manifest_document,
    MANIFEST_JSON_SCHEMA,
)
from coolbox.console.dashboard import TEXTUAL_AVAILABLE
from coolbox.paths import ensure_directory, artifacts_dir, project_root
from coolbox.setup import (
    SetupOrchestrator,
    SetupResult,
    SetupRunJournal,
    SetupStage,
    SetupStatus,
    load_last_run,
)
from coolbox.setup.recipes import Recipe, RecipeLoader
from coolbox.setup.stages import register_builtin_tasks
from coolbox.utils import launch_vm_debug
from coolbox.telemetry import JsonlTelemetryStorage, TelemetryClient, TelemetryConsentManager
from .default_manifest import get_default_manifest


@dataclass(slots=True)
class ManifestProfile:
    """Resolved manifest profile information."""

    name: str
    orchestrator: Mapping[str, Any]
    preload: Mapping[str, Any]
    recovery: Mapping[str, Any]
    plugins: tuple[PluginDefinition, ...]
    dev: ProfileDevSettings


class BootManager:
    """Coordinate CLI parsing, setup orchestration and application launch."""

    def __init__(
        self,
        *,
        manifest_path: Path | os.PathLike[str] | str | Traversable | None = None,
        app_factory: Callable[[], Any] | None = None,
        orchestrator_factory: Callable[[], SetupOrchestrator] | None = None,
        recipe_loader: RecipeLoader | None = None,
        dependency_checker: Callable[[Path | None], bool] | None = None,
        logger: logging.Logger | None = None,
        telemetry: TelemetryClient | None = None,
        consent_manager: TelemetryConsentManager | None = None,
        telemetry_storage: JsonlTelemetryStorage | None = None,
    ) -> None:
        self._default_manifest = self._coerce_manifest(manifest_path)
        self.app_factory = app_factory
        self._orchestrator_factory = orchestrator_factory or self._default_orchestrator_factory
        self.consent_manager = consent_manager or TelemetryConsentManager()
        if telemetry is not None:
            self.telemetry = telemetry
        else:
            storage_path = ensure_directory(artifacts_dir()) / "telemetry.jsonl"
            storage = telemetry_storage or JsonlTelemetryStorage(storage_path)
            self.telemetry = TelemetryClient(storage)
        self.orchestrator = self._orchestrator_factory()
        if hasattr(self.orchestrator, "attach_telemetry"):
            self.orchestrator.attach_telemetry(self.telemetry)
        if not getattr(self.orchestrator, "tasks", None):
            register_builtin_tasks(self.orchestrator)
        self.recipe_loader = recipe_loader or RecipeLoader()
        self.dependency_checker = dependency_checker
        self.logger = logger or logging.getLogger("coolbox.boot.manager")
        self._manifest_cache: dict[str, ManifestProfile] = {}
        self._manifest_validator = Draft7Validator(MANIFEST_JSON_SCHEMA)
        self._manifest_document: BootManifest | None = None
        self._last_recipe: Recipe | None = None

    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_manifest(
        manifest: Path | os.PathLike[str] | str | Traversable | None,
    ) -> Path | Traversable | None:
        if manifest is None:
            return None
        if isinstance(manifest, Path):
            return manifest
        if isinstance(manifest, (str, os.PathLike)):
            return Path(manifest)
        if isinstance(manifest, Traversable):
            return manifest
        raise TypeError(f"Unsupported manifest type: {type(manifest)!r}")

    @staticmethod
    def _default_orchestrator_factory() -> SetupOrchestrator:
        root = project_root()
        return SetupOrchestrator(root=root)

    @staticmethod
    def _default_root() -> Path:
        return project_root()

    # ------------------------------------------------------------------
    def run(self, argv: Sequence[str] | None = None) -> None:
        """Execute the full boot pipeline."""

        args = self._parse_args(argv)
        if args.boot_manifest is not None:
            self._default_manifest = Path(args.boot_manifest)
            self._manifest_cache.clear()
            self._manifest_document = None

        self.logger.debug("Boot arguments parsed", extra={"argv": list(argv or [])})

        if args.vm_debug:
            self.logger.info("Launching VM debug helper")
            launch_vm_debug(
                prefer=None if args.vm_prefer == "auto" else args.vm_prefer,
                open_code=args.open_code,
                port=args.debug_port,
            )
            return

        if args.debug:
            self._initialize_debugger(args.debug_port)

        if self.dependency_checker:
            try:
                self.dependency_checker(self._default_root())
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.exception("Dependency check failed", exc_info=exc)
                raise

        profile = self._load_profile(args.profile)
        consent = self.consent_manager.ensure_opt_in()
        if consent.granted and isinstance(self.telemetry, TelemetryClient):
            metadata = {"profile": profile.name}
            if self._default_manifest:
                metadata["manifest"] = str(self._default_manifest)
            self.telemetry.record_environment(metadata)
            self.telemetry.record_consent(granted=True, source=consent.source)
        else:
            if isinstance(self.telemetry, TelemetryClient):
                self.telemetry.disable()
        self.logger.debug("Selected boot profile", extra={"profile": profile.name})

        recipe_name = args.setup_recipe or profile.orchestrator.get("recipe")
        stages = self._resolve_stages(profile.orchestrator.get("stages"))
        task_names = self._resolve_task_names(profile.orchestrator.get("tasks"))
        plugin_definitions = profile.plugins
        load_flag = profile.orchestrator.get("load_plugins")
        if load_flag is False:
            plugin_payload: Sequence[PluginDefinition] | None = ()
        elif plugin_definitions:
            plugin_payload = plugin_definitions
        else:
            plugin_payload = None

        if not (args.debug or args.vm_debug):
            self._preload_components(
                modules=profile.preload.get("modules", []),
                callables=profile.preload.get("callables", []),
            )
        else:
            self.logger.debug("Skipping preload due to debugger/VM flags")

        try:
            recipe = self._load_recipe(recipe_name)
            self._execute_setup(
                recipe,
                stages=stages,
                task_names=task_names,
                plugins=plugin_payload,
                dev=profile.dev,
            )
            self._launch_application()
        except Exception as exc:
            self.logger.exception("Application launch failed; entering recovery console", exc_info=exc)
            self._fallback_to_console(exc, profile)
        finally:
            if isinstance(self.telemetry, TelemetryClient):
                self.telemetry.flush()

    # ------------------------------------------------------------------
    def _parse_args(self, argv: Sequence[str] | None) -> Namespace:
        parser = ArgumentParser(description="CoolBox application")
        parser.add_argument("--debug", action="store_true", help="Run under debugpy and wait for debugger to attach")
        parser.add_argument(
            "--debug-port",
            type=int,
            default=5678,
            help="Port for debugpy or --vm-debug listener (default: 5678)",
        )
        parser.add_argument(
            "--vm-debug",
            action="store_true",
            help="Launch inside a VM or container and wait for debugger",
        )
        parser.add_argument(
            "--vm-prefer",
            choices=["docker", "vagrant", "podman", "auto"],
            default="auto",
            help="Preferred VM backend for --vm-debug",
        )
        parser.add_argument(
            "--open-code",
            action="store_true",
            help="Open VS Code when launching --vm-debug",
        )
        parser.add_argument(
            "--setup-recipe",
            type=str,
            default=None,
            help="Path or name of the setup recipe to apply before launching CoolBox",
        )
        parser.add_argument(
            "--profile",
            type=str,
            default="default",
            help="Startup profile defined in the boot manifest",
        )
        parser.add_argument(
            "--boot-manifest",
            type=Path,
            default=None,
            help="Override the boot manifest path",
        )
        return parser.parse_args(list(argv) if argv is not None else None)

    # ------------------------------------------------------------------
    def _initialize_debugger(self, port: int) -> None:
        try:
            import debugpy

            debugpy.listen(port)
            self.logger.info("Waiting for debugger on port %s...", port)
            debugpy.wait_for_client()
        except Exception as exc:  # pragma: no cover - debug only
            self.logger.warning("Failed to start debugpy: %s", exc)

    # ------------------------------------------------------------------
    def _load_manifest(self) -> Mapping[str, Any]:
        manifest_path = self._default_manifest
        if manifest_path is None:
            self.logger.debug("Boot manifest not specified; using bundled defaults")
            return get_default_manifest()

        exists = False
        try:
            if isinstance(manifest_path, Path):
                exists = manifest_path.exists()
            else:
                exists = manifest_path.is_file()
        except OSError as exc:
            self.logger.warning("Unable to access boot manifest %s: %s", manifest_path, exc)
            self.logger.debug("Boot manifest not accessible, using bundled defaults")
            return get_default_manifest()

        if not exists:
            self.logger.debug("Boot manifest not found, using empty configuration")
            self.logger.debug("Boot manifest missing, using bundled defaults")
            return get_default_manifest()

        try:
            text = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - file permissions
            self.logger.warning("Unable to read boot manifest %s: %s", manifest_path, exc)
            return get_default_manifest()
        data: Mapping[str, Any]
        if yaml is not None:
            data = yaml.safe_load(text) or {}
        else:
            try:
                data = json.loads(text or "{}")
            except json.JSONDecodeError as exc:
                data = self._manifest_from_missing_yaml(manifest_path, exc)
        if not isinstance(data, Mapping):
            raise TypeError("Boot manifest must contain a mapping")
        return data

    def _get_manifest_document(self) -> BootManifest:
        if self._manifest_document is not None:
            return self._manifest_document
        raw = self._load_manifest()
        try:
            self._manifest_validator.validate(raw)
        except ValidationError as exc:
            pointer = "/".join(str(part) for part in exc.path)
            message = exc.message
            if pointer:
                message = f"{message} (at {pointer})"
            raise ManifestValidationError(message) from exc
        try:
            manifest = load_manifest_document(raw)
        except PluginManifestError as exc:
            raise ManifestValidationError(str(exc)) from exc
        self._manifest_cache.clear()
        self._manifest_document = manifest
        return manifest

    def _manifest_from_missing_yaml(
        self,
        manifest_path: Path | Traversable,
        error: json.JSONDecodeError,
    ) -> Mapping[str, Any]:
        """Return a manifest when PyYAML is unavailable."""

        manifest_name = getattr(manifest_path, "name", None)
        manifest_display = str(manifest_path)
        if manifest_name is None:
            manifest_name = Path(manifest_display).name

        if manifest_name == "boot_manifest.yaml":
            self.logger.warning(
                "PyYAML not installed; using bundled boot manifest defaults."
            )
            return get_default_manifest()

        raise RuntimeError(
            "Unable to parse boot manifest without PyYAML: "
            f"{manifest_display}. Install PyYAML or provide a JSON manifest."
        ) from error

    def _load_profile(self, name: str) -> ManifestProfile:
        if name in self._manifest_cache:
            return self._manifest_cache[name]
        manifest = self._get_manifest_document()
        profiles = manifest.profiles
        if name not in profiles:
            available = ", ".join(sorted(profiles)) or "<none>"
            raise ValueError(f"Boot profile '{name}' not found (available: {available})")
        profile_doc: ManifestBootProfile = profiles[name]
        profile = ManifestProfile(
            name=name,
            orchestrator=dict(profile_doc.orchestrator),
            preload=dict(profile_doc.preload),
            recovery=dict(profile_doc.recovery),
            plugins=profile_doc.plugins,
            dev=profile_doc.dev,
        )
        self._manifest_cache[name] = profile
        return profile

    # ------------------------------------------------------------------
    def _resolve_stages(self, raw: Any) -> Sequence[SetupStage] | None:
        if raw is None:
            return None
        if not isinstance(raw, Iterable):
            self.logger.warning("Invalid stage list in manifest: %r", raw)
            return None
        stages: list[SetupStage] = []
        for entry in raw:
            try:
                stages.append(SetupStage(str(entry)))
            except ValueError:
                try:
                    stages.append(SetupStage[str(entry).upper()])
                except KeyError:
                    self.logger.warning("Unknown setup stage '%s' in manifest", entry)
        return stages or None

    def _resolve_task_names(self, raw: Any) -> Sequence[str] | None:
        if raw is None:
            return None
        if not isinstance(raw, Iterable):
            self.logger.warning("Invalid task list in manifest: %r", raw)
            return None
        names = [str(item) for item in raw]
        return names or None

    # ------------------------------------------------------------------
    def _preload_components(self, *, modules: Iterable[str], callables: Iterable[str]) -> None:
        module_list = [str(module) for module in modules]
        callable_list = [str(spec) for spec in callables]
        if not module_list and not callable_list:
            return
        self.logger.debug(
            "Preloading components",
            extra={"modules": module_list, "callables": callable_list},
        )

        async def _runner() -> None:
            tasks = []
            for module in module_list:
                tasks.append(asyncio.to_thread(self._import_module, module))
            for spec in callable_list:
                tasks.append(asyncio.to_thread(self._invoke_callable, spec))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        try:
            asyncio.run(_runner())
        except RuntimeError as exc:  # event loop already running
            self.logger.debug("Async preload encountered active loop: %s", exc)
            thread = threading.Thread(target=lambda: asyncio.run(_runner()), daemon=True)
            thread.start()
            thread.join()

    def _import_module(self, name: str) -> None:
        try:
            importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - import failures logged
            self.logger.warning("Failed to preload module %s: %s", name, exc)

    def _invoke_callable(self, spec: str) -> None:
        module_name, _, attr = spec.partition(":")
        if not module_name or not attr:
            self.logger.warning("Invalid preload callable specification: %s", spec)
            return
        try:
            module = importlib.import_module(module_name)
            target = getattr(module, attr)
            if callable(target):
                target()
            else:
                self.logger.warning("Preload target %s is not callable", spec)
        except Exception as exc:  # pragma: no cover - import/call failures logged
            self.logger.warning("Failed to execute preload callable %s: %s", spec, exc)

    # ------------------------------------------------------------------
    def _load_recipe(self, recipe_name: str | None) -> Recipe:
        recipe = self.recipe_loader.load(recipe_name)
        self._last_recipe = recipe
        return recipe

    def _execute_setup(
        self,
        recipe: Recipe,
        *,
        stages: Sequence[SetupStage] | None,
        task_names: Sequence[str] | None,
        plugins: Sequence[PluginDefinition] | None,
        dev: ProfileDevSettings | None,
    ) -> list[SetupResult]:
        resume_journal: SetupRunJournal | None = None
        if stages and self._last_recipe and recipe.name == self._last_recipe.name:
            journal = load_last_run(self.orchestrator.root)
            if journal and (journal.metadata.get("recipe_name") == recipe.name or not journal.metadata):
                resume_journal = journal
                self.logger.debug("Resuming setup from journal %s", journal.path)
                self.orchestrator.resume_from_journal(journal)
                self.orchestrator.replay_events(journal.iter_events())
        results = self.orchestrator.run(
            recipe,
            stages=stages,
            task_names=task_names,
            plugins=plugins,
            dev=dev,
        )
        if resume_journal is not None:
            # Ensure the orchestrator preserves the resume context for subsequent recovery attempts.
            self.orchestrator.resume_from_journal(None)
        failures = [result for result in results if result.status is SetupStatus.FAILED]
        if failures:
            summary = ", ".join(
                f"{failure.task}:{failure.stage.value}" for failure in failures
            )
            raise RuntimeError(f"Setup orchestration failed for tasks: {summary}")
        return results

    # ------------------------------------------------------------------
    def _launch_application(self) -> None:
        factory = self.app_factory
        if factory is None:
            raise RuntimeError("No application factory configured")
        app = factory()
        if not hasattr(app, "run"):
            raise TypeError("Application factory must return an object with a 'run' method")
        app.run()

    # ------------------------------------------------------------------
    def _fallback_to_console(self, exc: Exception, profile: ManifestProfile) -> None:
        recovery = profile.recovery or {}
        dashboard_cfg = recovery.get("dashboard", {}) if isinstance(recovery, Mapping) else {}
        mode = str(dashboard_cfg.get("mode") or ("textual" if TEXTUAL_AVAILABLE else "json"))
        theme_name = str(dashboard_cfg.get("theme") or DashboardTheme.MINIMAL.value)
        layout_name = str(dashboard_cfg.get("layout") or DashboardLayout.MINIMAL.value)
        try:
            theme = DashboardTheme(theme_name)
        except ValueError:
            theme = DashboardTheme.MINIMAL
        try:
            layout = DashboardLayout(layout_name)
        except ValueError:
            layout = DashboardLayout.MINIMAL
        knowledge = getattr(self.telemetry, "knowledge", None)
        dashboard = create_dashboard(
            self.orchestrator,
            mode=mode,
            layout=layout,
            theme=theme,
            knowledge_base=knowledge,
        )
        dashboard.start()
        hints = recovery.get("hints", []) if isinstance(recovery, Mapping) else []
        hint_text = "\n".join(str(hint) for hint in hints) if hints else "Review setup diagnostics and retry launch."
        message = f"GUI failed to launch: {exc}. {hint_text}"
        try:
            dashboard.handle_event(LogEvent("error", message, payload={"exception": repr(exc)}))
            stages = self._resolve_stages(recovery.get("stages")) if isinstance(recovery, Mapping) else None
            if stages and self._last_recipe is not None:
                try:
                    self.logger.info("Running recovery stages: %s", ", ".join(stage.value for stage in stages))
                    self._execute_setup(
                        self._last_recipe,
                        stages=stages,
                        task_names=None,
                        plugins=profile.plugins,
                        dev=profile.dev,
                    )
                except Exception as recovery_exc:  # pragma: no cover - diagnostics only
                    dashboard.handle_event(
                        LogEvent(
                            "error",
                            f"Recovery stages failed: {recovery_exc}",
                            payload={"exception": repr(recovery_exc)},
                        )
                    )
        finally:
            dashboard.stop()

