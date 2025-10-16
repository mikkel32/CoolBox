#!/usr/bin/env python3
"""CoolBox main entry point that delegates boot orchestration."""
import sys
import hashlib
import importlib.util
from pathlib import Path
import logging
from typing import Iterable

from importlib import metadata as importlib_metadata
from packaging.requirements import Requirement

from src.boot import BootManager
from src.utils.logging_config import setup_logging

# Ensure package imports work when running as a script before other imports.
sys.path.insert(0, str(Path(__file__).parent))

from src import CoolBoxApp  # noqa: E402
from src.setup.orchestrator import SetupOrchestrator, SetupStatus
from src.setup.recipes import RecipeLoader
from src.setup.stages import register_builtin_tasks


def _default_root() -> Path:
    return Path(__file__).resolve().parent


def _parse_requirements(req_path: Path) -> Iterable[str]:
    if not req_path.is_file():
        return ()
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def _missing_requirements(req_path: Path) -> list[str]:
    missing: list[str] = []
    for entry in _parse_requirements(req_path):
        requirement = Requirement(entry)
        try:
            version = importlib_metadata.version(requirement.name)
        except importlib_metadata.PackageNotFoundError:
            missing.append(entry)
            continue
        if requirement.specifier and version not in requirement.specifier:
            missing.append(entry)
    return missing


def _requirements_satisfied(req_path: Path) -> bool:
    return not _missing_requirements(req_path)


def _compute_setup_state(root: Path | None = None) -> str:
    target_root = Path(root or _default_root()).resolve()
    digest = hashlib.sha256()
    for name in ("requirements.txt", "setup.py"):
        path = target_root / name
        if not path.is_file():
            continue
        digest.update(str(path.stat().st_mtime_ns).encode())
        digest.update(path.read_bytes())
    pyver = f"{sys.executable}:{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
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


def _run_setup_if_needed(root: Path | None = None) -> bool:
    target_root = Path(root or _default_root()).resolve()
    requirements = target_root / "requirements.txt"
    sentinel = target_root / ".setup_done"
    digest = _compute_setup_state(target_root)
    recorded = None
    if sentinel.is_file():
        try:
            recorded = sentinel.read_text(encoding="utf-8").strip()
        except OSError:
            recorded = None

    missing = _missing_requirements(requirements)
    should_run = recorded != digest or bool(missing)
    if not should_run:
        return False

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
        logger = logging.getLogger(__name__)
        logger.warning("Could not update setup sentinel at %s", sentinel)
    return True


logger = logging.getLogger(__name__)


def _run_setup(recipe_name: str | None) -> None:
    root = Path(__file__).resolve().parent
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
    """Initialize logging and delegate to :class:`BootManager`."""

    setup_logging()
    manager = BootManager(
        manifest_path=Path(__file__).resolve().parent / "assets" / "boot_manifest.yaml",
        app_factory=CoolBoxApp,
        dependency_checker=_run_setup_if_needed,
    )
    manager.run(list(argv) if argv is not None else None)


if __name__ == "__main__":
    main()
