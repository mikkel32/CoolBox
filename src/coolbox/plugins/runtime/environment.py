"""Provisioning helpers for plugin runtime environments."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import venv

from coolbox.paths import artifacts_dir, ensure_directory, project_root
from coolbox.plugins.manifest import PluginDefinition, RuntimeBuild, RuntimeConfiguration


@dataclass(slots=True)
class RuntimeActivation:
    """Details required to activate a provisioned runtime environment."""

    venv_dir: Path
    bin_dir: Path
    site_packages: tuple[Path, ...]

    def apply(self) -> None:
        """Apply the activation permanently to the current process."""

        _ensure_site_packages_exist(self.site_packages)
        os.environ["VIRTUAL_ENV"] = str(self.venv_dir)
        bin_entry = str(self.bin_dir)
        path_entries = os.environ.get("PATH", "").split(os.pathsep) if os.environ.get("PATH") else []
        if bin_entry not in path_entries:
            path_entries.insert(0, bin_entry)
            os.environ["PATH"] = os.pathsep.join(path_entries) if path_entries else bin_entry
        pythonpath_entries = [str(path) for path in self.site_packages if path]
        if pythonpath_entries:
            existing_pythonpath = os.environ.get("PYTHONPATH", "")
            combined = pythonpath_entries + ([existing_pythonpath] if existing_pythonpath else [])
            os.environ["PYTHONPATH"] = os.pathsep.join(combined)
        for path in reversed(self.site_packages):
            str_path = str(path)
            if str_path and str_path not in sys.path:
                sys.path.insert(0, str_path)

    @contextmanager
    def temporary(self) -> Iterator[None]:
        """Temporarily apply the activation, restoring on exit."""

        previous_env = {
            "PATH": os.environ.get("PATH"),
            "PYTHONPATH": os.environ.get("PYTHONPATH"),
            "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV"),
        }
        previous_sys_path = list(sys.path)
        self.apply()
        try:
            yield
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            sys.path[:] = previous_sys_path

    def to_payload(self) -> dict[str, object]:
        """Return a serialisable payload for multiprocessing hand-off."""

        return {
            "venv_dir": str(self.venv_dir),
            "bin_dir": str(self.bin_dir),
            "site_packages": [str(path) for path in self.site_packages],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "RuntimeActivation":
        """Reconstruct activation metadata from :meth:`to_payload`."""

        venv_dir = Path(str(payload["venv_dir"]))
        bin_dir = Path(str(payload["bin_dir"]))
        site_packages = tuple(Path(str(path)) for path in payload.get("site_packages", ()))
        return cls(venv_dir=venv_dir, bin_dir=bin_dir, site_packages=site_packages)


@dataclass(slots=True)
class PluginRuntimeEnvironment:
    """Provisioned environment state for a plugin runtime."""

    root: Path
    venv_dir: Path
    lock_path: Path
    activation: RuntimeActivation | None


def ensure_runtime_environment(definition: PluginDefinition) -> PluginRuntimeEnvironment:
    """Ensure the plugin runtime environment is provisioned and return metadata."""

    root = ensure_directory(_plugin_root(definition.identifier))
    venv_dir = root / "venv"
    _ensure_venv(venv_dir)
    site_packages = tuple(_select_site_packages(venv_dir))
    activation = RuntimeActivation(
        venv_dir=venv_dir,
        bin_dir=_venv_bin_dir(venv_dir),
        site_packages=site_packages,
    )
    lock_path = root / "lock.json"
    metadata = _environment_metadata(definition.runtime, definition.identifier)
    _write_lockfile(lock_path, metadata, definition.runtime.build)
    return PluginRuntimeEnvironment(root=root, venv_dir=venv_dir, lock_path=lock_path, activation=activation)


def apply_runtime_activation(payload: Mapping[str, object] | None) -> None:
    """Apply runtime activation from a payload, if provided."""

    if not payload:
        return
    activation = RuntimeActivation.from_payload(payload)
    activation.apply()


def _plugin_root(identifier: str) -> Path:
    return ensure_directory(artifacts_dir() / "plugins" / identifier)


def _ensure_venv(target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        return
    builder = venv.EnvBuilder(with_pip=True, clear=False, upgrade=False)
    builder.create(str(target))


def _venv_bin_dir(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts"
    return venv_dir / "bin"


def _candidate_site_packages(venv_dir: Path) -> Iterable[Path]:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return (
        venv_dir / "Lib" / "site-packages",
        venv_dir / "Lib64" / "site-packages",
        venv_dir / "lib" / version / "site-packages",
        venv_dir / "lib64" / version / "site-packages",
        venv_dir / "lib" / version / "dist-packages",
        venv_dir / "lib64" / version / "dist-packages",
    )


def _select_site_packages(venv_dir: Path) -> Iterable[Path]:
    created = False
    for candidate in _candidate_site_packages(venv_dir):
        if candidate.exists():
            yield candidate
            created = True
    if not created:
        default_path = venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        ensure_directory(default_path)
        yield default_path


def _ensure_site_packages_exist(paths: Iterable[Path]) -> None:
    for path in paths:
        ensure_directory(path)


def _environment_metadata(runtime: RuntimeConfiguration, plugin_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "plugin": plugin_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime.kind,
        "environment": dict(runtime.environment),
    }
    if runtime.interpreter:
        payload["interpreter"] = {
            "python": list(runtime.interpreter.python),
            "implementation": runtime.interpreter.implementation,
            "platforms": list(runtime.interpreter.platforms),
            "extras": dict(runtime.interpreter.extras),
        }
    if runtime.runtimes:
        payload["requires_runtimes"] = list(runtime.runtimes)
    if runtime.wasm:
        payload["wasm"] = {
            "module": str(runtime.wasm.module),
            "runtimes": list(runtime.wasm.runtimes),
            "entrypoint": runtime.wasm.entrypoint,
        }
    return payload


def _write_lockfile(target: Path, metadata: Mapping[str, object], build: RuntimeBuild | None) -> None:
    payload = dict(metadata)
    if build is not None:
        payload["build"] = {
            "steps": [
                {
                    "name": step.name,
                    "command": list(step.command),
                    "shell": step.shell,
                    "cwd": str(step.cwd) if step.cwd else None,
                    "environment": dict(step.environment),
                }
                for step in build.steps
            ],
            "lockfile": str(build.lockfile) if build.lockfile else None,
        }
        if build.lockfile:
            _mirror_declared_lockfile(build.lockfile, target.parent)
    ensure_directory(target.parent)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def _mirror_declared_lockfile(source: Path, root: Path) -> None:
    resolved = source if source.is_absolute() else project_root() / source
    if not resolved.exists():
        return
    destination = root / resolved.name
    if destination.exists():
        return
    destination.write_bytes(resolved.read_bytes())


__all__ = [
    "PluginRuntimeEnvironment",
    "RuntimeActivation",
    "apply_runtime_activation",
    "ensure_runtime_environment",
]

