from __future__ import annotations

from types import SimpleNamespace

import json

import pytest

from coolbox.boot.manager import BootManager
from coolbox.paths import asset_path


class _DummyApp:
    def run(self) -> None:  # pragma: no cover - not used in tests
        pass


class _DummyOrchestrator:
    tasks = [object()]

    def attach_telemetry(self, telemetry) -> None:  # pragma: no cover - noop
        self.telemetry = telemetry


class _DummyTelemetry:
    knowledge = None

    def disable(self) -> None:  # pragma: no cover - noop
        pass

    def record_environment(self, *_args, **_kwargs) -> None:  # pragma: no cover - noop
        pass

    def record_consent(self, *_args, **_kwargs) -> None:  # pragma: no cover - noop
        pass

    def flush(self) -> None:  # pragma: no cover - noop
        pass


class _DummyConsentManager:
    def ensure_opt_in(self):  # pragma: no cover - simple stub
        return SimpleNamespace(granted=False, source="tests")


def _make_manager(manifest_path):
    return BootManager(
        manifest_path=manifest_path,
        app_factory=_DummyApp,
        orchestrator_factory=_DummyOrchestrator,
        recipe_loader=SimpleNamespace(load=lambda _name: None),
        dependency_checker=None,
        telemetry=_DummyTelemetry(),
        consent_manager=_DummyConsentManager(),
    )


def test_load_manifest_without_yaml_uses_fallback(monkeypatch, caplog):
    monkeypatch.setattr("coolbox.boot.manager.yaml", None)
    manager = _make_manager(asset_path("boot_manifest.yaml"))

    with caplog.at_level("WARNING"):
        manifest = manager._load_manifest()

    assert "PyYAML not installed" in caplog.text
    assert manifest["profiles"]["default"]["orchestrator"]["stages"][0] == "preflight"


def test_load_manifest_without_yaml_requires_json(tmp_path, monkeypatch):
    monkeypatch.setattr("coolbox.boot.manager.yaml", None)
    custom_manifest = tmp_path / "custom.yaml"
    custom_manifest.write_text("profiles:\n  demo: {}\n", encoding="utf-8")
    manager = _make_manager(custom_manifest)

    with pytest.raises(RuntimeError) as excinfo:
        manager._load_manifest()

    assert "Install PyYAML" in str(excinfo.value)


def test_minimal_manifest_applies_defaults(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "minimal": {
                        "plugins": [
                            {
                                "id": "demo-plugin",
                                "runtime": {
                                    "kind": "native",
                                    "entrypoint": "coolbox.setup.plugins:NullPlugin",
                                },
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(manifest_path)

    profile = manager._load_profile("minimal")

    assert profile.orchestrator == {}
    assert profile.preload == {}
    assert profile.recovery == {}
    assert len(profile.plugins) == 1
    plugin = profile.plugins[0]
    assert plugin.capabilities.provides == ()
    assert plugin.capabilities.requires == ()
    assert plugin.capabilities.sandbox == ()
    assert plugin.resources.cpu is None
    assert plugin.resources.memory is None
    assert plugin.hooks.before == ()
    assert plugin.hooks.after == ()
    assert plugin.hooks.on_failure == ()
