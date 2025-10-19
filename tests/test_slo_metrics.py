"""Tests for SLO tracker persistence."""

from __future__ import annotations

import pytest

from coolbox.catalog import get_catalog, reset_catalog
from coolbox.telemetry.slo import get_slo_tracker


@pytest.fixture(autouse=True)
def _configure_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_PROJECT_ROOT", str(tmp_path))
    from coolbox import paths

    paths.project_root.cache_clear()
    paths.artifacts_dir.cache_clear()
    reset_catalog()
    yield
    paths.project_root.cache_clear()
    paths.artifacts_dir.cache_clear()
    reset_catalog()


def test_slo_metrics_recorded(monkeypatch):
    tracker = get_slo_tracker()
    tracker.reset()

    # Simulate deterministic timing for perf_counter measurements.
    times = [100.0, 100.5, 101.0]

    def fake_perf_counter():
        return times[0]

    monkeypatch.setattr("coolbox.telemetry.slo.time.perf_counter", fake_perf_counter)
    tracker.start_run(profile="default")

    times[0] = 100.5
    tracker.record_ttff()

    times[0] = 101.0
    tracker.record_plugin_spawn("demo")
    tracker.record_tool_invocation("demo", duration=0.2)

    catalog = get_catalog()
    metrics = catalog.export_bundle()["metrics"]
    metric_names = {entry["metric"] for entry in metrics}
    assert {"ttff_ms", "plugin_cold_start_ms", "tool_latency_p95_ms"}.issubset(metric_names)

    plugin_metrics = [entry for entry in metrics if entry["metric"] == "tool_latency_p95_ms"]
    assert plugin_metrics
    assert plugin_metrics[0]["metadata"]["plugin_id"] == "demo"
