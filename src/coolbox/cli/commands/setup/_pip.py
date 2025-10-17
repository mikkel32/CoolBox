"""Installation helpers and wheel cache management."""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Sequence

from sys import modules

from ._execution import _retry, _run
from ._logging import log
from ._state import (
    DEV_PACKAGES,
    ROOT_DIR,
    STAMP_CACHE_ROOT,
    WHEEL_CACHE_ROOT,
    get_venv_dir,
    is_offline,
)
from ._summary import SUMMARY
from ._ui import create_progress
from ._venv import ensure_venv

__all__ = [
    "_available_wheel_links",
    "_build_install_plan",
    "_execute_install_plan",
    "_pip",
    "_restore_wheel_artifacts",
    "_store_wheel_artifacts",
    "_write_req_stamp",
]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stamp_path() -> Path:
    return get_venv_dir() / ".req_hash"


def _global_stamp_path(req_hash: str) -> Path:
    return STAMP_CACHE_ROOT / f"{req_hash}.stamp"


def _hydrate_stamp_from_cache(req_hash: str, target: Path) -> None:
    cached = _global_stamp_path(req_hash)
    if cached.is_file():
        try:
            target.write_text(cached.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass


def _store_stamp_to_cache(req_hash: str) -> None:
    cached = _global_stamp_path(req_hash)
    try:
        cached.write_text(req_hash, encoding="utf-8")
    except Exception:
        pass


def _should_install(requirements: Path, upgrade: bool) -> bool:
    if upgrade:
        return True
    if not requirements.exists():
        return False
    req_hash = _file_hash(requirements)
    stamp = _stamp_path()
    if not stamp.exists():
        _hydrate_stamp_from_cache(req_hash, stamp)
    try:
        recorded = stamp.read_text().strip()
    except Exception:
        return True
    return recorded != req_hash


def _write_req_stamp(requirements: Path) -> None:
    req_hash = _file_hash(requirements)
    target = _stamp_path()
    target.write_text(req_hash, encoding="utf-8")
    _store_stamp_to_cache(req_hash)


def _wheel_cache_key() -> str:
    digest = hashlib.sha256()
    for name in ("pyproject.toml", "setup.py"):
        path = ROOT_DIR / name
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _wheel_cache_dir() -> Path:
    path = WHEEL_CACHE_ROOT / _wheel_cache_key()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store_wheel_artifacts(dist_dir: Path) -> None:
    if not dist_dir.exists():
        return
    cache_dir = _wheel_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for item in dist_dir.glob("*.whl"):
        try:
            shutil.copy2(item, cache_dir / item.name)
        except Exception:
            continue


def _restore_wheel_artifacts(dist_dir: Path) -> bool:
    cache_dir = _wheel_cache_dir()
    if not cache_dir.exists():
        return False
    dist_dir.mkdir(parents=True, exist_ok=True)
    restored = False
    for item in cache_dir.glob("*.whl"):
        try:
            shutil.copy2(item, dist_dir / item.name)
            restored = True
        except Exception:
            continue
    return restored


def _available_wheel_links() -> list[str]:
    links: list[str] = []
    if WHEEL_CACHE_ROOT.exists():
        for candidate in [WHEEL_CACHE_ROOT, *WHEEL_CACHE_ROOT.glob("*")]:
            if candidate.is_dir():
                links.append(str(candidate))
    return links


def _pip(
    args: Sequence[str],
    python: str | Path | None = None,
    *,
    upgrade_pip: bool = False,
    attempts: int = 2,
) -> None:
    py = str(python or ensure_venv())
    base_cmd = [py, "-m", "pip"]
    env_override: dict[str, str] = {}
    offline = is_offline()
    setup_module = modules.get("coolbox.cli.commands.setup")
    if setup_module is not None:
        links_fn = getattr(setup_module, "_available_wheel_links", _available_wheel_links)
    else:
        links_fn = _available_wheel_links
    links = list(links_fn())
    if offline:
        offline_args: list[str] = ["--no-index"]
        if not links:
            SUMMARY.add_warning(
                "Offline mode enabled but wheel cache is empty; pip command may fail."
            )
        for link in links:
            offline_args.extend(["--find-links", link])
        if links:
            env_override["PIP_FIND_LINKS"] = os.pathsep.join(links)
        env_override["PIP_NO_INDEX"] = "1"
        cmd = base_cmd + list(args) + offline_args
        log("Offline mode: forcing pip to use cached wheels.")
    else:
        cmd = base_cmd + list(args)
        if upgrade_pip:
            _retry(
                base_cmd + ["install", "-U", "pip", "setuptools", "wheel"],
                attempts=attempts,
                env=env_override,
            )
    if offline and upgrade_pip:
        SUMMARY.add_warning("Offline mode: skipping pip bootstrap upgrade.")
    if upgrade_pip:
        env_override.setdefault("PIP_DEFAULT_TIMEOUT", "60")
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _run(cmd, env=env_override or None)
            return
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(0.8 * attempt)
    if last is not None:
        raise last


def _build_install_plan(
    requirements: Path,
    dev: bool,
    upgrade: bool,
) -> list[tuple[str, list[str], bool]]:
    plan: list[tuple[str, list[str], bool]] = []
    if requirements.is_file():
        if _should_install(requirements, upgrade):
            args = ["install", "-r", str(requirements)]
            if upgrade:
                args.append("-U")
            plan.append(("Install requirements", args, True))
        else:
            log("Requirements unchanged. Skipping install.")
    else:
        SUMMARY.add_warning(f"Requirements file missing: {requirements}")
    if dev:
        dev_req = ROOT_DIR / "requirements-dev.txt"
        if dev_req.is_file():
            args = ["install", "-r", str(dev_req)]
            if upgrade:
                args.append("-U")
            plan.append(("Install dev requirements", args, True))
        else:
            for package in DEV_PACKAGES:
                args = ["install", package]
                if upgrade:
                    args.append("-U")
                plan.append((f"Install {package}", args, False))
    return plan


def _execute_install_plan(planned: Sequence[tuple[str, list[str], bool]]) -> None:
    if not planned:
        return
    with create_progress() as progress:
        task = progress.add_task("Executing install plan", total=len(planned))
        for title, pip_args, upgrade_pip in planned:
            progress.update(task, description=title)
            try:
                _pip(pip_args, upgrade_pip=upgrade_pip, attempts=3)
            except Exception as exc:
                SUMMARY.add_error(f"{title} failed: {exc}")
            progress.advance(task)
