"""Command-line bootstrap utilities for CoolBox."""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import sys
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Iterable

from packaging.requirements import Requirement

from coolbox.boot import BootManager
from coolbox.paths import asset_path, project_root
from coolbox.setup.orchestrator import SetupOrchestrator, SetupStatus
from coolbox.setup.recipes import RecipeLoader
from coolbox.setup.stages import register_builtin_tasks
from coolbox.utils.logging_config import setup_logging
from coolbox.cli.commands.setup._state import release_lightweight_mode

logger = logging.getLogger(__name__)


def default_root() -> Path:
    """Return the project root regardless of installation layout."""

    return project_root()


def parse_requirements(req_path: Path) -> Iterable[str]:
    """Yield requirement specifiers from ``req_path``.

    Empty lines and comments are ignored so the helper can be reused by tests.
    """

    if not req_path.is_file():
        return ()

    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def missing_requirements(req_path: Path) -> list[str]:
    """Return requirement entries that are missing or out-of-spec."""

    missing: list[str] = []
    for entry in parse_requirements(req_path):
        requirement = Requirement(entry)
        try:
            version = importlib_metadata.version(requirement.name)
        except importlib_metadata.PackageNotFoundError:
            missing.append(entry)
            continue

        if requirement.specifier and version not in requirement.specifier:
            missing.append(entry)
    return missing


def requirements_satisfied(req_path: Path) -> bool:
    """Return ``True`` when all requirements from ``req_path`` are met."""

    return not missing_requirements(req_path)


def compute_setup_state(root: Path | None = None) -> str:
    """Return a hash representing the state that triggers auto-setup."""

    target_root = Path(root or default_root()).resolve()
    digest = hashlib.sha256()

    for name in ("requirements.txt", "setup.py"):
        path = target_root / name
        if not path.is_file():
            continue
        digest.update(str(path.stat().st_mtime_ns).encode())
        digest.update(path.read_bytes())

    pyver = (
        f"{sys.executable}:{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    digest.update(pyver.encode())
    return digest.hexdigest()


def _load_setup_module(root: Path) -> object:
    path = root / "setup.py"
    if not path.exists():
        raise FileNotFoundError(path)

    spec = importlib.util.spec_from_file_location("coolbox_setup", path)
    if not spec or not spec.loader:  # pragma: no cover - defensive
        raise RuntimeError(f"Unable to load setup.py from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def run_setup_if_needed(root: Path | None = None) -> bool:
    """Execute the project bootstrapper when dependencies changed."""

    target_root = Path(root or default_root()).resolve()
    requirements = target_root / "requirements.txt"
    sentinel = target_root / ".setup_done"

    digest = compute_setup_state(target_root)
    recorded = None
    if sentinel.is_file():
        try:
            recorded = sentinel.read_text(encoding="utf-8").strip()
        except OSError:
            recorded = None

    missing = missing_requirements(requirements)
    should_run = recorded != digest or bool(missing)
    ran = False

    try:
        if not should_run:
            return ran

        module = _load_setup_module(target_root)
        banner = getattr(module, "show_setup_banner", None)
        if callable(banner):
            banner()

        check_python = getattr(module, "check_python_version", None)
        if callable(check_python):
            check_python()

        installer = getattr(module, "install", None)
        if callable(installer):
            try:
                installer(skip_update=True)
            except TypeError:
                installer()

        try:
            sentinel.write_text(digest, encoding="utf-8")
        except OSError:  # pragma: no cover - defensive
            logger.warning("Could not update setup sentinel at %s", sentinel)
        ran = True
        return ran
    finally:
        if release_lightweight_mode():
            logger.debug("Re-enabled full application mode after setup run")


def run_setup(recipe_name: str | None) -> None:
    """Invoke the setup orchestrator for the provided recipe."""

    root = default_root()
    loader = RecipeLoader()
    try:
        recipe = loader.load(recipe_name)
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        logger.error("Unable to load setup recipe %s: %s", recipe_name, exc)
        raise

    orchestrator = SetupOrchestrator(root=root)
    register_builtin_tasks(orchestrator)
    results = orchestrator.run(recipe)
    failures = [r for r in results if r.status is SetupStatus.FAILED]
    if failures:
        summary = ", ".join(f"{f.task}:{f.stage.value}" for f in failures)
        raise RuntimeError(f"Setup orchestration failed for tasks: {summary}")


def main(argv: Iterable[str] | None = None) -> None:
    """Entry point used by ``python -m coolbox`` and the legacy ``main.py``."""

    setup_logging()
    if release_lightweight_mode():
        logger.debug("Re-enabled full application mode for GUI launch")
    from coolbox.app import CoolBoxApp  # local import to avoid circular dependency during module import
    manifest_resource = asset_path("boot_manifest.yaml")
    manager = BootManager(
        manifest_path=manifest_resource,
        app_factory=CoolBoxApp,
        dependency_checker=run_setup_if_needed,
    )
    argv_list = list(argv) if argv is not None else []
    manager.run(argv_list)
    if (
        not manager.launched_application
        and not manager.launch_deferred
        and not argv_list
    ):
        logger.warning(
            "Boot pipeline exited without launching the UI; attempting direct start"
        )
        app = CoolBoxApp()
        app.run()


__all__ = [
    "compute_setup_state",
    "default_root",
    "main",
    "missing_requirements",
    "parse_requirements",
    "requirements_satisfied",
    "run_setup",
    "run_setup_if_needed",
]
