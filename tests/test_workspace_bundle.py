"""Tests for workspace bundle export/import commands."""

from __future__ import annotations

import json
import shutil

import pytest

from coolbox.catalog import get_catalog, reset_catalog
from coolbox.cli.commands import workspace_bundle
from coolbox.paths import artifacts_dir
from coolbox.plugins.manifest import (
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ResourceBudget,
    RuntimeConfiguration,
    StartupHooks,
)


def _build_definition(identifier: str = "demo") -> PluginDefinition:
    runtime = RuntimeConfiguration(kind="native")
    capabilities = PluginCapabilities((), (), ())
    io_schema = PluginIOSchema(inputs={}, outputs={})
    resources = ResourceBudget(cpu=None, memory=None, disk=None, gpu=None, timeout=None)
    hooks = StartupHooks((), (), ())
    dev = PluginDevSettings(False, (), ())
    return PluginDefinition(
        identifier=identifier,
        runtime=runtime,
        capabilities=capabilities,
        io=io_schema,
        resources=resources,
        hooks=hooks,
        dev=dev,
        version="1.0.0",
        description="Demo plugin",
    )


@pytest.fixture(autouse=True)
def _reset_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_PROJECT_ROOT", str(tmp_path))
    from coolbox import paths

    paths.project_root.cache_clear()
    paths.artifacts_dir.cache_clear()
    reset_catalog()
    yield
    paths.project_root.cache_clear()
    paths.artifacts_dir.cache_clear()
    reset_catalog()


def test_workspace_bundle_roundtrip(tmp_path):
    catalog = get_catalog()
    definition = _build_definition()
    catalog.record_manifest("default", definition, manifest_path="manifest.yaml")
    catalog.record_configuration({"foo": "bar"})
    catalog.record_plugin_trace(
        "demo",
        method="before_stage",
        status="ok",
        duration=0.5,
        timestamp=123.0,
        trace_id=None,
        error=None,
    )
    catalog.record_startup_metric("run-1", "ttff_ms", 150.0, metadata={"profile": "default"})

    diag_dir = artifacts_dir() / "plugins" / "demo" / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    (diag_dir / "sample.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    bundle_path = tmp_path / "bundle.zip"
    workspace_bundle._export_bundle(bundle_path)
    assert bundle_path.is_file()

    # Reset state and remove artifacts before importing
    reset_catalog()
    from coolbox import paths

    paths.artifacts_dir.cache_clear()
    artifacts = artifacts_dir()
    if artifacts.exists():
        shutil.rmtree(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)

    workspace_bundle._import_bundle(bundle_path)

    restored_catalog = get_catalog()
    manifests = restored_catalog.manifest_records()
    assert any(record["plugin_id"] == "demo" for record in manifests)
    config = restored_catalog.latest_configuration()
    assert config["foo"] == "bar"
    traces = list(restored_catalog.iter_plugin_traces("demo"))
    assert traces and traces[0]["status"] == "ok"
    metrics = restored_catalog.export_bundle()["metrics"]
    assert any(entry["metric"] == "ttff_ms" for entry in metrics)

    restored_diag = artifacts_dir() / "plugins" / "demo" / "diagnostics"
    assert any(restored_diag.iterdir())
