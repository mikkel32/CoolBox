"""Builtin setup stages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
from typing import Any, Sequence

from importlib import metadata as importlib_metadata
from packaging.requirements import Requirement

from .orchestrator import (
    SetupResult,
    SetupStage,
    SetupStatus,
    SetupTask,
    StageContext,
)


_SENTINEL_KEY = "setup.sentinel"
_DIGEST_KEY = "setup.digest"
_SKIP_KEY = "setup.skip"
_SHOULD_INSTALL_KEY = "setup.should_install"
_MISSING_KEY = "setup.missing"
_MODULE_KEY = "setup.module"


def register_builtin_tasks(orchestrator: "SetupOrchestrator") -> None:
    """Register the default set of setup tasks."""

    orchestrator.register_tasks(
        [
            SetupTask("preflight.env", SetupStage.PREFLIGHT, _preflight_environment),
            SetupTask("preflight.digest", SetupStage.PREFLIGHT, _preflight_digest),
            SetupTask("dependency.requirements", SetupStage.DEPENDENCY_RESOLUTION, _dependency_resolution),
            SetupTask("install.run", SetupStage.INSTALLERS, _run_installers),
            SetupTask("verify.environment", SetupStage.VERIFICATION, _verify_install),
            SetupTask("summary.render", SetupStage.SUMMARIES, _summaries),
        ]
    )


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def _preflight_environment(context: StageContext) -> dict[str, Any]:
    config = context.recipe.config
    sentinel = context.root / config.get("sentinel", ".setup_done")
    context.set(_SENTINEL_KEY, sentinel)
    skip = os.environ.get("SKIP_SETUP") == "1"
    context.set(_SKIP_KEY, skip)
    return {
        "sentinel": str(sentinel),
        "skip": skip,
        "recipe": context.recipe.name,
    }


def _preflight_digest(context: StageContext) -> SetupResult:
    if context.get(_SKIP_KEY):
        return SetupResult(
            task="preflight.digest",
            stage=SetupStage.PREFLIGHT,
            status=SetupStatus.SKIPPED,
            payload={"reason": "SKIP_SETUP"},
        )
    config = context.recipe.config
    requirements = context.root / config.get("requirements", "requirements.txt")
    digest = _compute_setup_state(context.root, ("requirements.txt", "setup.py"))
    context.set(_DIGEST_KEY, digest)
    recorded = None
    sentinel: Path = context.get(_SENTINEL_KEY)
    if sentinel.is_file():
        try:
            recorded = sentinel.read_text(encoding="utf-8").strip()
        except Exception as exc:
            recorded = None
            context.orchestrator.logger.debug("Failed to read sentinel %s: %s", sentinel, exc)
    should_run = config.get("force", False) or recorded != digest
    context.set(_SHOULD_INSTALL_KEY, should_run)
    payload = {
        "requirements": str(requirements),
        "digest": digest,
        "sentinel_match": recorded == digest,
        "should_install": should_run,
    }
    return SetupResult(
        task="preflight.digest",
        stage=SetupStage.PREFLIGHT,
        status=SetupStatus.SUCCESS,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------

def _dependency_resolution(context: StageContext) -> SetupResult:
    if context.get(_SKIP_KEY):
        context.set(_SHOULD_INSTALL_KEY, False)
        return SetupResult(
            task="dependency.requirements",
            stage=SetupStage.DEPENDENCY_RESOLUTION,
            status=SetupStatus.SKIPPED,
            payload={"reason": "SKIP_SETUP"},
        )
    config = context.recipe.config
    requirements = context.root / config.get("requirements", "requirements.txt")
    missing = _missing_requirements(requirements)
    context.set(_MISSING_KEY, missing)
    should_install = context.get(_SHOULD_INSTALL_KEY, False) or bool(missing)
    if config.get("force", False):
        should_install = True
    context.set(_SHOULD_INSTALL_KEY, should_install)
    payload = {
        "requirements": str(requirements),
        "missing": missing,
        "should_install": should_install,
    }
    status = SetupStatus.SUCCESS
    if not should_install and not missing:
        status = SetupStatus.SKIPPED
    return SetupResult(
        task="dependency.requirements",
        stage=SetupStage.DEPENDENCY_RESOLUTION,
        status=status,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Installers
# ---------------------------------------------------------------------------

def _run_installers(context: StageContext) -> SetupResult:
    if context.get(_SKIP_KEY):
        return SetupResult(
            task="install.run",
            stage=SetupStage.INSTALLERS,
            status=SetupStatus.SKIPPED,
            payload={"reason": "SKIP_SETUP"},
        )
    if not context.get(_SHOULD_INSTALL_KEY, False):
        return SetupResult(
            task="install.run",
            stage=SetupStage.INSTALLERS,
            status=SetupStatus.SKIPPED,
            payload={"reason": "cache-valid"},
        )
    module = _load_setup_module(context)
    config = context.recipe.config
    requirements = context.root / config.get("requirements", "requirements.txt")
    install_cfg = dict(config)
    skip_update = install_cfg.get("skip_update", True)
    kwargs = {
        "requirements": requirements if requirements.exists() else None,
        "dev": bool(install_cfg.get("dev", False)),
        "upgrade": bool(install_cfg.get("upgrade", False)),
        "skip_update": skip_update,
        "no_anim": install_cfg.get("no_anim"),
        "border": install_cfg.get("border"),
        "alt_screen": install_cfg.get("alt_screen"),
    }
    try:
        if hasattr(module, "show_setup_banner"):
            module.show_setup_banner()
        if hasattr(module, "check_python_version"):
            module.check_python_version()
        if hasattr(module, "install"):
            module.install(**kwargs)
    except Exception as exc:  # pragma: no cover - defensive
        return SetupResult(
            task="install.run",
            stage=SetupStage.INSTALLERS,
            status=SetupStatus.FAILED,
            payload={"kwargs": _stringify(kwargs)},
            error=exc,
        )
    payload = {
        "module": getattr(module, "__name__", "setup"),
        "kwargs": _stringify(kwargs),
    }
    return SetupResult(
        task="install.run",
        stage=SetupStage.INSTALLERS,
        status=SetupStatus.SUCCESS,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _verify_install(context: StageContext) -> SetupResult:
    sentinel: Path = context.get(_SENTINEL_KEY)
    digest: str | None = context.get(_DIGEST_KEY)
    config = context.recipe.config
    if context.get(_SKIP_KEY):
        if config.get("write_sentinel_on_skip", False) and digest:
            try:
                sentinel.write_text(digest, encoding="utf-8")
            except Exception as exc:
                context.orchestrator.logger.debug("Failed to write sentinel %s: %s", sentinel, exc)
        return SetupResult(
            task="verify.environment",
            stage=SetupStage.VERIFICATION,
            status=SetupStatus.SKIPPED,
            payload={"reason": "SKIP_SETUP"},
        )
    requirements = context.root / config.get("requirements", "requirements.txt")
    missing = _missing_requirements(requirements)
    context.set("setup.missing_after", missing)
    if not missing and digest:
        try:
            sentinel.write_text(digest, encoding="utf-8")
        except Exception as exc:
            context.orchestrator.logger.warning("Could not update sentinel %s: %s", sentinel, exc)
    status = SetupStatus.SUCCESS if not missing else SetupStatus.FAILED
    payload = {
        "missing": missing,
        "sentinel": str(sentinel),
    }
    return SetupResult(
        task="verify.environment",
        stage=SetupStage.VERIFICATION,
        status=status,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summaries(context: StageContext) -> SetupResult:
    results = list(context.results.values())
    payload = {
        "recipe": context.recipe.name,
        "failed": [r.task for r in results if r.status is SetupStatus.FAILED],
        "skipped": [r.task for r in results if r.status is SetupStatus.SKIPPED],
        "config": context.recipe.config,
    }
    status = SetupStatus.SUCCESS
    if payload["failed"]:
        status = SetupStatus.FAILED
    return SetupResult(
        task="summary.render",
        stage=SetupStage.SUMMARIES,
        status=status,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_setup_state(root: Path, filenames: Sequence[str]) -> str:
    h = hashlib.sha256()
    for name in filenames:
        fp = root / name
        if not fp.is_file():
            continue
        h.update(str(fp.stat().st_mtime_ns).encode())
        h.update(fp.read_bytes())
    pyver = (
        f"{sys.executable}:{sys.version_info.major}" f".{sys.version_info.minor}.{sys.version_info.micro}"
    )
    h.update(pyver.encode())
    return h.hexdigest()


def _parse_requirements(req_path: Path) -> list[str]:
    if not req_path.is_file():
        return []
    reqs: list[str] = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        reqs.append(line)
    return reqs


def _missing_requirements(req_path: Path) -> list[str]:
    reqs = _parse_requirements(req_path)
    if not reqs:
        return []
    missing: list[str] = []
    with ThreadPoolExecutor() as ex:
        for result in ex.map(_check_single_requirement, reqs):
            if result:
                missing.append(result)
    return missing


def _check_single_requirement(req: str) -> str | None:
    requirement = Requirement(req)
    try:
        version = importlib_metadata.version(requirement.name)
    except importlib_metadata.PackageNotFoundError:
        return req
    if requirement.specifier and version not in requirement.specifier:
        return req
    return None


def _load_setup_module(context: StageContext):
    module = context.get(_MODULE_KEY)
    if module is not None:
        return module
    path = context.root / "setup.py"
    spec = importlib.util.spec_from_file_location("coolbox_setup", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load setup.py from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    context.set(_MODULE_KEY, module)
    return module


def _stringify(data: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, Path) else v for k, v in data.items() if v is not None}


__all__ = ["register_builtin_tasks"]
