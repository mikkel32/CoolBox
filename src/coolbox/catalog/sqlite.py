"""SQLite-backed catalog implementation for persisted runtime metadata."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from coolbox.paths import artifacts_dir, ensure_directory

try:  # pragma: no cover - optional import for static typing only
    from typing import TYPE_CHECKING
except ImportError:  # pragma: no cover - Python <3.11 fallback
    TYPE_CHECKING = False  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from coolbox.plugins.manifest import PluginDefinition


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _definition_payload(definition: "PluginDefinition") -> dict[str, Any]:
    """Normalise :class:`PluginDefinition` into a JSON-serialisable mapping."""

    runtime = {
        "kind": definition.runtime.kind,
        "entrypoint": definition.runtime.entrypoint,
        "module": definition.runtime.module,
        "handler": definition.runtime.handler,
        "wasi": bool(definition.runtime.wasi),
        "features": list(definition.runtime.features),
        "environment": dict(definition.runtime.environment),
        "runtimes": list(definition.runtime.runtimes),
        "wasm": None,
        "lockfile": str(definition.runtime.lockfile) if definition.runtime.lockfile else None,
    }
    if definition.runtime.wasm is not None:
        runtime["wasm"] = {
            "module": str(definition.runtime.wasm.module),
            "runtimes": list(definition.runtime.wasm.runtimes),
            "entrypoint": definition.runtime.wasm.entrypoint,
        }
    interpreter = definition.runtime.interpreter
    if interpreter is not None:
        runtime["interpreter"] = {
            "python": list(interpreter.python),
            "implementation": interpreter.implementation,
            "platforms": list(interpreter.platforms),
            "extras": dict(interpreter.extras),
        }
    build = definition.runtime.build
    if build is not None:
        runtime["build"] = {
            "steps": [
                {
                    "name": step.name,
                    "command": list(step.command),
                    "shell": bool(step.shell),
                    "cwd": str(step.cwd) if step.cwd else None,
                    "environment": dict(step.environment),
                }
                for step in build.steps
            ]
        }

    capabilities = {
        "provides": list(definition.capabilities.provides),
        "requires": list(definition.capabilities.requires),
        "sandbox": list(definition.capabilities.sandbox),
    }
    io_schema = {
        "inputs": dict(definition.io.inputs),
        "outputs": dict(definition.io.outputs),
    }
    resources = {
        "cpu": definition.resources.cpu,
        "memory": definition.resources.memory,
        "disk": definition.resources.disk,
        "gpu": definition.resources.gpu,
        "timeout": definition.resources.timeout,
    }
    hooks = {
        "before": list(definition.hooks.before),
        "after": list(definition.hooks.after),
        "on_failure": list(definition.hooks.on_failure),
    }
    dev = {
        "hot_reload": bool(definition.dev.hot_reload),
        "watch_paths": [str(path) for path in definition.dev.watch_paths],
        "locales": list(definition.dev.locales),
    }
    toolbus = None
    if definition.toolbus is not None:
        toolbus = {
            "invoke": dict(definition.toolbus.invoke),
            "stream": dict(definition.toolbus.stream),
            "subscribe": dict(definition.toolbus.subscribe),
        }
    return {
        "identifier": definition.identifier,
        "version": definition.version,
        "description": definition.description,
        "runtime": runtime,
        "capabilities": capabilities,
        "io": io_schema,
        "resources": resources,
        "hooks": hooks,
        "dev": dev,
        "toolbus": toolbus,
    }


class Catalog:
    """Lightweight wrapper around the SQLite catalog database."""

    def __init__(self, db_path: Path | None = None) -> None:
        base = ensure_directory(artifacts_dir()) if db_path is None else db_path.parent
        self.path = db_path or (base / "state.db")
        ensure_directory(self.path.parent)
        self._lock = threading.RLock()
        self._initialised = False

    # ------------------------------------------------------------------
    def _initialise(self) -> None:
        if self._initialised:
            return
        connection = sqlite3.connect(self.path)
        try:
            cursor = connection.cursor()
            cursor.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS manifest_plugins (
                    profile TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    version TEXT,
                    definition TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    manifest_path TEXT,
                    PRIMARY KEY (profile, plugin_id)
                );
                CREATE TABLE IF NOT EXISTS configuration_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configuration_latest (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS plugin_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plugin_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    trace_id TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_plugin_traces_plugin_ts
                    ON plugin_traces(plugin_id, timestamp DESC);
                CREATE TABLE IF NOT EXISTS startup_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    captured_at REAL NOT NULL,
                    metadata TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_startup_metrics_run
                    ON startup_metrics(run_id, metric);
                """
            )
            connection.commit()
        finally:
            connection.close()
        self._initialised = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._initialise()
        connection = sqlite3.connect(self.path)
        try:
            yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------------
    def record_manifest(
        self,
        profile: str,
        definition: "PluginDefinition",
        *,
        manifest_path: str | None = None,
    ) -> None:
        payload = _definition_payload(definition)
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO manifest_plugins(profile, plugin_id, version, definition, recorded_at, manifest_path)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile, plugin_id)
                DO UPDATE SET
                    version=excluded.version,
                    definition=excluded.definition,
                    recorded_at=excluded.recorded_at,
                    manifest_path=excluded.manifest_path
                """,
                (
                    profile,
                    definition.identifier,
                    definition.version,
                    _json_dumps(payload),
                    now,
                    manifest_path,
                ),
            )
            connection.commit()

    def record_configuration(self, config: Mapping[str, Any]) -> None:
        timestamp = time.time()
        payload = _json_dumps(dict(config))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO configuration_snapshots(captured_at, payload) VALUES(?, ?)",
                (timestamp, payload),
            )
            cursor = connection.cursor()
            for key, value in config.items():
                cursor.execute(
                    """
                    INSERT INTO configuration_latest(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (str(key), _json_dumps(value)),
                )
            connection.commit()

    def record_plugin_trace(
        self,
        plugin_id: str,
        *,
        method: str,
        status: str,
        duration: float,
        timestamp: float,
        trace_id: str | None,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plugin_traces(plugin_id, method, status, duration, timestamp, trace_id, error)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (plugin_id, method, status, duration, timestamp, trace_id, error),
            )
            connection.commit()

    def record_startup_metric(
        self,
        run_id: str,
        metric: str,
        value: float,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO startup_metrics(run_id, metric, value, captured_at, metadata)
                VALUES(?, ?, ?, ?, ?)
                """,
                (run_id, metric, float(value), time.time(), _json_dumps(metadata or {})),
            )
            connection.commit()

    # ------------------------------------------------------------------
    def latest_configuration(self) -> Mapping[str, Any]:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT key, value FROM configuration_latest")
            rows = cursor.fetchall()
        return {key: _json_loads(value) for key, value in rows}

    def iter_plugin_traces(self, plugin_id: str) -> Iterable[Mapping[str, Any]]:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT method, status, duration, timestamp, trace_id, error FROM plugin_traces WHERE plugin_id=? ORDER BY timestamp",
                (plugin_id,),
            )
            for method, status, duration, timestamp, trace_id, error in cursor.fetchall():
                yield {
                    "plugin_id": plugin_id,
                    "method": method,
                    "status": status,
                    "duration": duration,
                    "timestamp": timestamp,
                    "trace_id": trace_id,
                    "error": error,
                }

    def manifest_records(self) -> Sequence[Mapping[str, Any]]:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT profile, plugin_id, version, definition, recorded_at, manifest_path FROM manifest_plugins"
            )
            rows = cursor.fetchall()
        return [
            {
                "profile": profile,
                "plugin_id": plugin_id,
                "version": version,
                "definition": json.loads(definition),
                "recorded_at": recorded_at,
                "manifest_path": manifest_path,
            }
            for profile, plugin_id, version, definition, recorded_at, manifest_path in rows
        ]

    def manifest_for_plugin(self, plugin_id: str) -> Mapping[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT profile, version, definition, recorded_at, manifest_path
                FROM manifest_plugins
                WHERE plugin_id=?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                (plugin_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        profile, version, definition, recorded_at, manifest_path = row
        return {
            "profile": profile,
            "plugin_id": plugin_id,
            "version": version,
            "definition": json.loads(definition),
            "recorded_at": recorded_at,
            "manifest_path": manifest_path,
        }

    def export_bundle(self) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT captured_at, payload FROM configuration_snapshots ORDER BY captured_at DESC")
            config_rows = cursor.fetchall()
            cursor.execute(
                "SELECT plugin_id, method, status, duration, timestamp, trace_id, error FROM plugin_traces ORDER BY id"
            )
            trace_rows = cursor.fetchall()
            cursor.execute(
                "SELECT run_id, metric, value, captured_at, metadata FROM startup_metrics ORDER BY id"
            )
            metric_rows = cursor.fetchall()
            cursor.execute(
                "SELECT profile, plugin_id, version, definition, recorded_at, manifest_path FROM manifest_plugins"
            )
            manifest_rows = cursor.fetchall()
        bundle = {
            "configuration": [
                {"captured_at": ts, "payload": json.loads(payload)} for ts, payload in config_rows
            ],
            "traces": [
                {
                    "plugin_id": plugin_id,
                    "method": method,
                    "status": status,
                    "duration": duration,
                    "timestamp": timestamp,
                    "trace_id": trace_id,
                    "error": error,
                }
                for plugin_id, method, status, duration, timestamp, trace_id, error in trace_rows
            ],
            "metrics": [
                {
                    "run_id": run_id,
                    "metric": metric,
                    "value": value,
                    "captured_at": captured_at,
                    "metadata": json.loads(metadata) if metadata else {},
                }
                for run_id, metric, value, captured_at, metadata in metric_rows
            ],
            "manifest": [
                {
                    "profile": profile,
                    "plugin_id": plugin_id,
                    "version": version,
                    "definition": json.loads(definition),
                    "recorded_at": recorded_at,
                    "manifest_path": manifest_path,
                }
                for profile, plugin_id, version, definition, recorded_at, manifest_path in manifest_rows
            ],
        }
        return bundle

    def import_bundle(self, payload: Mapping[str, Any]) -> None:
        manifest_entries = payload.get("manifest", [])
        trace_entries = payload.get("traces", [])
        config_entries = payload.get("configuration", [])
        metric_entries = payload.get("metrics", [])
        with self._connect() as connection:
            cursor = connection.cursor()
            for entry in manifest_entries:
                cursor.execute(
                    """
                    INSERT INTO manifest_plugins(profile, plugin_id, version, definition, recorded_at, manifest_path)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile, plugin_id)
                    DO UPDATE SET
                        version=excluded.version,
                        definition=excluded.definition,
                        recorded_at=excluded.recorded_at,
                        manifest_path=excluded.manifest_path
                    """,
                    (
                        entry.get("profile"),
                        entry.get("plugin_id"),
                        entry.get("version"),
                        _json_dumps(entry.get("definition")),
                        float(entry.get("recorded_at", time.time())),
                        entry.get("manifest_path"),
                    ),
                )
            for entry in config_entries:
                cursor.execute(
                    "INSERT INTO configuration_snapshots(captured_at, payload) VALUES(?, ?)",
                    (float(entry.get("captured_at", time.time())), _json_dumps(entry.get("payload", {}))),
                )
            for entry in metric_entries:
                cursor.execute(
                    "INSERT INTO startup_metrics(run_id, metric, value, captured_at, metadata) VALUES(?, ?, ?, ?, ?)",
                    (
                        entry.get("run_id"),
                        entry.get("metric"),
                        float(entry.get("value", 0.0)),
                        float(entry.get("captured_at", time.time())),
                        _json_dumps(entry.get("metadata", {})),
                    ),
                )
            for entry in trace_entries:
                cursor.execute(
                    "INSERT INTO plugin_traces(plugin_id, method, status, duration, timestamp, trace_id, error) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.get("plugin_id"),
                        entry.get("method"),
                        entry.get("status"),
                        float(entry.get("duration", 0.0)),
                        float(entry.get("timestamp", time.time())),
                        entry.get("trace_id"),
                        entry.get("error"),
                    ),
                )
            connection.commit()


_CATALOG_SINGLETON: Catalog | None = None
_CATALOG_LOCK = threading.RLock()


def get_catalog() -> Catalog:
    global _CATALOG_SINGLETON
    with _CATALOG_LOCK:
        if _CATALOG_SINGLETON is None:
            _CATALOG_SINGLETON = Catalog()
        return _CATALOG_SINGLETON


def reset_catalog() -> None:
    global _CATALOG_SINGLETON
    with _CATALOG_LOCK:
        _CATALOG_SINGLETON = None

