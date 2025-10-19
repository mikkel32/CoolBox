"""Tests for the application infrastructure helpers."""
from __future__ import annotations

import logging
import threading

import pytest

from coolbox.app import infrastructure as infra_module
from coolbox.app.infrastructure import (
    AppInfrastructure,
    HealthCheckResult,
    ResiliencePolicy,
    ServiceModule,
    ServiceRegistry,
    ServiceLifetime,
    ServiceHealthStatus,
    ServiceTopology,
)
from coolbox.utils.thread_manager import ThreadManager


class DummyWidget:
    def __init__(self) -> None:
        self.fonts_refreshed = 0
        self.theme_refreshed = 0
        self._exists = True

    def winfo_exists(self) -> bool:
        return self._exists

    def refresh_fonts(self) -> None:  # pragma: no cover - used indirectly
        self.fonts_refreshed += 1

    def refresh_theme(self) -> None:  # pragma: no cover - used indirectly
        self.theme_refreshed += 1

    def destroy(self) -> None:
        self._exists = False


def test_service_registry_resolve_and_shutdown() -> None:
    registry = ServiceRegistry()
    tear_down_called = []

    registry.register("value", lambda reg: object(), eager=True)
    registry.register(
        "tracked",
        lambda reg: {"thread": threading.current_thread().name},
        eager=True,
        on_close=lambda data: tear_down_called.append(data["thread"]),
    )

    first = registry.resolve("value")
    second = registry.resolve("value")
    assert first is second  # cached
    tracked = registry.resolve("tracked")
    assert tracked["thread"].startswith("MainThread")

    registry.shutdown()
    assert tear_down_called == ["MainThread"]


def test_service_registry_scoped_lifetime() -> None:
    registry = ServiceRegistry()
    shutdown_trace: list[str] = []

    counter = {"value": 0}

    def factory(_: ServiceRegistry) -> dict[str, int]:
        counter["value"] += 1
        return {"token": counter["value"]}

    registry.register(
        "scoped",
        factory,
        lifetime=ServiceLifetime.SCOPED,
        on_close=lambda payload: shutdown_trace.append(f"closed-{payload['token']}")
        if isinstance(payload, dict)
        else shutdown_trace.append("closed-unknown"),
    )

    scope_a = registry.create_scope("session")
    scope_b = registry.create_scope("session")

    a_first = scope_a.resolve("scoped")
    a_second = scope_a.resolve("scoped")
    b_first = scope_b.resolve("scoped")

    assert a_first is a_second
    assert a_first is not b_first

    scope_a.close()
    assert shutdown_trace == ["closed-1"]

    scope_b.close()
    assert shutdown_trace == ["closed-1", "closed-2"]


def test_service_registry_replace_invokes_shutdown() -> None:
    registry = ServiceRegistry()
    shutdown_trace: list[str] = []

    registry.register(
        "value",
        lambda reg: {"version": 1},
        eager=True,
        on_close=lambda payload: shutdown_trace.append(f"close-{payload['version']}")
        if isinstance(payload, dict)
        else shutdown_trace.append("close-unknown"),
    )

    registry.register(
        "value",
        lambda reg: {"version": 2},
        eager=True,
        replace=True,
        on_close=lambda payload: shutdown_trace.append(f"replacement-{payload['version']}")
        if isinstance(payload, dict)
        else shutdown_trace.append("replacement-unknown"),
    )

    assert shutdown_trace == ["close-1"]
    assert registry.resolve("value")["version"] == 2


def test_service_registry_unregister_disposes_instance() -> None:
    registry = ServiceRegistry()
    disposed: list[str] = []

    registry.register_instance(
        "value",
        {"id": 1},
        on_close=lambda payload: disposed.append(f"disposed-{payload['id']}")
        if isinstance(payload, dict)
        else disposed.append("disposed-unknown"),
    )

    registry.unregister("value")

    assert disposed == ["disposed-1"]
    with pytest.raises(KeyError):
        registry.unregister("value")


def test_service_registry_health_checks() -> None:
    registry = ServiceRegistry()

    registry.register(
        "healthy",
        lambda reg: {"ready": True},
        health_check=lambda instance, reg: HealthCheckResult(True, "ready", 0.01),
        critical=True,
    )

    registry.register(
        "failing",
        lambda reg: {"ready": False},
        health_check=lambda instance, reg: (False, "broken"),
    )

    healthy_status = registry.check_health("healthy")
    assert healthy_status.healthy is True
    assert healthy_status.checked is True
    assert healthy_status.critical is True
    assert healthy_status.details == "ready"
    assert healthy_status.source == "health_check"

    failing_status = registry.check_health("failing")
    assert failing_status.healthy is False
    assert failing_status.checked is True
    assert failing_status.details == "broken"

    registry.register(
        "unstable",
        lambda reg: (_ for _ in ()).throw(RuntimeError("boom")),
        health_check=lambda instance, reg: True,
    )

    with pytest.raises(RuntimeError):
        registry.check_health("unstable")

    tolerant = registry.check_health("unstable", tolerate_failures=True)
    assert tolerant.healthy is False
    assert tolerant.details and "Resolution failed" in tolerant.details


def test_service_registry_health_snapshot_and_topology() -> None:
    registry = ServiceRegistry()

    registry.register("a", lambda reg: "a")
    registry.register("b", lambda reg: "b", dependencies=("a",))
    registry.register("c", lambda reg: "c", dependencies=("b", "missing"))
    registry.register("cycle1", lambda reg: "one", dependencies=("cycle2",))
    registry.register("cycle2", lambda reg: "two", dependencies=("cycle1",))

    snapshot = registry.health_snapshot()
    assert all(isinstance(status, ServiceHealthStatus) for status in snapshot)
    assert any(status.name == "a" for status in snapshot)

    topology = registry.service_topology()
    assert isinstance(topology, ServiceTopology)
    assert "a" in topology.activation_order
    assert "a" in topology.roots
    assert "c" in topology.missing_dependencies
    assert "missing" in topology.missing_dependencies["c"]
    assert any({"cycle1", "cycle2"} <= set(cycle) for cycle in topology.cycles)


def test_service_registry_rejects_operations_after_shutdown() -> None:
    registry = ServiceRegistry()
    registry.register("value", lambda reg: 42)
    registry.shutdown()

    with pytest.raises(RuntimeError):
        registry.register("other", lambda reg: "nope")

    with pytest.raises(RuntimeError):
        registry.resolve("value")

    with pytest.raises(RuntimeError):
        registry.unregister("value")


def test_service_registry_resolution_events_and_observers() -> None:
    registry = ServiceRegistry()
    observed: list[infra_module.ServiceResolutionEvent] = []

    registry.add_resolution_observer(observed.append)
    with pytest.raises(ValueError):
        registry.add_resolution_observer(observed.append)

    registry.register("singleton", lambda reg: {"token": object()})
    first = registry.resolve("singleton")
    second = registry.resolve("singleton")

    assert first is second
    history = registry.resolution_history()
    assert len(history) >= 2
    assert history[-1].from_cache is True
    assert observed[-1] == history[-1]

    registry.clear_resolution_history()
    observed.clear()

    def broken(_: ServiceRegistry) -> object:
        raise RuntimeError("boom")

    registry.register("broken", broken)
    with pytest.raises(RuntimeError):
        registry.resolve("broken")

    failure_history = registry.resolution_history()
    assert failure_history[-1].success is False
    assert "RuntimeError" in (failure_history[-1].error or "")
    assert observed[-1] is failure_history[-1]

    registry.remove_resolution_observer(observed.append)
    with pytest.raises(KeyError):
        registry.remove_resolution_observer(observed.append)


def test_service_registry_resilience_retries_and_metrics() -> None:
    registry = ServiceRegistry()
    attempts = {"count": 0}

    policy = ResiliencePolicy(max_attempts=3, retry_exceptions=(RuntimeError,))

    def flaky(_: ServiceRegistry) -> dict[str, int]:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("transient failure")
        return {"attempt": attempts["count"]}

    registry.register("flaky", flaky, resilience=policy)

    resolved = registry.resolve("flaky")
    assert resolved["attempt"] == 2

    metrics = registry.service_metrics()["flaky"]
    assert metrics.retries == 1
    assert metrics.last_attempts == 2
    events = [event for event in registry.resolution_history() if event.name == "flaky"]
    assert any(event.retry_scheduled for event in events)
    assert any(event.success and event.recovered for event in events)


def test_service_registry_resilience_fallback_recovers() -> None:
    registry = ServiceRegistry()

    policy = ResiliencePolicy(
        max_attempts=1,
        retry_exceptions=(RuntimeError,),
        fallback=lambda reg, exc: {"value": "fallback"},
    )

    def broken(_: ServiceRegistry) -> dict[str, str]:
        raise RuntimeError("boom")

    registry.register("with-fallback", broken, resilience=policy)

    recovered = registry.resolve("with-fallback")
    assert recovered["value"] == "fallback"

    metrics = registry.service_metrics()["with-fallback"]
    assert metrics.fallback_uses == 1
    history = [event for event in registry.resolution_history() if event.name == "with-fallback"]
    assert len(history) == 1
    assert history[0].success is True and history[0].recovered is True


def test_service_registry_default_resilience_policy_applies() -> None:
    registry = ServiceRegistry()
    policy = ResiliencePolicy(max_attempts=2, retry_exceptions=(RuntimeError,))
    registry.set_default_resilience_policy(policy)

    attempts = {"count": 0}

    def flaky(_: ServiceRegistry) -> int:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("first attempt fails")
        return attempts["count"]

    registry.register("default-policy", flaky)

    assert registry.default_resilience_policy() is policy

    value = registry.resolve("default-policy")
    assert value == 2

    metrics = registry.service_metrics()["default-policy"]
    assert metrics.retries == 1
    resilience_info = registry.service_resilience_policies()["default-policy"]
    assert resilience_info is not None and resilience_info["max_attempts"] == 2


def test_service_registry_alias_resolution() -> None:
    registry = ServiceRegistry()
    registry.register("primary", lambda reg: {"answer": 42}, aliases=("alias",), tags={"core"})

    resolved_by_name = registry.resolve("primary")
    resolved_by_alias = registry.resolve("alias")

    assert resolved_by_name is resolved_by_alias
    assert registry.alias_map()["alias"] == "primary"
    assert "core" in registry.tags_index()


def test_service_registry_module_installation() -> None:
    registry = ServiceRegistry()

    core_module = ServiceModule(
        name="core",
        configure=lambda reg: reg.register("value", lambda _: 21 * 2),
        description="Provides the base numeric service.",
    )

    dependent_module = ServiceModule(
        name="dependent",
        dependencies=("core",),
        configure=lambda reg: reg.register("value-doubled", lambda r: r.resolve("value") * 2),
    )

    registry.install_module(core_module)
    registry.install_module(dependent_module)

    assert registry.resolve("value") == 42
    assert registry.resolve("value-doubled") == 84
    assert registry.installed_modules() == ("core", "dependent")
    assert registry.module_dependencies()["dependent"] == ("core",)
    assert registry.module_descriptions()["core"] == "Provides the base numeric service."

    replacement_module = ServiceModule(
        name="core",
        configure=lambda reg: reg.register("value", lambda _: 100, replace=True),
        description="Replacement core module.",
    )

    registry.install_module(replacement_module, replace=True)

    assert registry.resolve("value") == 100
    assert registry.module_descriptions()["core"] == "Replacement core module."

    with pytest.raises(ValueError):
        registry.install_module(core_module)

    with pytest.raises(RuntimeError):
        registry.install_module(
            ServiceModule(name="late", configure=lambda reg: None, dependencies=("missing",))
        )


def test_service_registry_dependency_and_metrics_tracking() -> None:
    registry = ServiceRegistry()
    order: list[str] = []

    def base_factory(reg: ServiceRegistry) -> dict[str, int]:
        order.append("base")
        return {"value": 42}

    def dependent_factory(reg: ServiceRegistry) -> dict[str, int]:
        order.append("dependent")
        base = reg.resolve("base")
        return {"value": base["value"] * 2}

    registry.register("base", base_factory, contract=dict)
    registry.register(
        "dependent",
        dependent_factory,
        dependencies=("base",),
        contract=dict,
    )

    result = registry.resolve("dependent")

    assert result == {"value": 84}
    assert order == ["base", "dependent"]
    assert registry.service_dependencies()["dependent"] == ("base",)
    metrics = registry.service_metrics()
    assert metrics["base"].created == 1
    assert metrics["dependent"].created == 1
    assert metrics["dependent"].failures == 0


def test_service_registry_detects_cycles() -> None:
    registry = ServiceRegistry()

    registry.register("a", lambda reg: object(), dependencies=("b",))
    registry.register("b", lambda reg: object(), dependencies=("a",))

    with pytest.raises(RuntimeError, match="Cyclic service dependency"):
        registry.resolve("a")


def test_service_registry_contract_and_validator_enforcement() -> None:
    registry = ServiceRegistry()

    registry.register("text", lambda reg: "hello", contract=dict)

    with pytest.raises(TypeError):
        registry.resolve("text")

    metrics = registry.service_metrics()["text"]
    assert metrics.contract_violations == 1
    assert metrics.failures == 1
    assert metrics.created == 0

    def validator(instance: dict[str, int], reg: ServiceRegistry) -> None:
        raise ValueError("broken")

    registry.register(
        "validated",
        lambda reg: {"value": 1},
        contract=dict,
        validator=validator,
    )

    with pytest.raises(ValueError, match="broken"):
        registry.resolve("validated")

    validated_metrics = registry.service_metrics()["validated"]
    assert validated_metrics.failures == 1
    assert validated_metrics.created == 0


def test_app_infrastructure_core_services_shutdown() -> None:
    app = object()
    infra = AppInfrastructure(app)

    config = infra.require("config")
    state = infra.require("app_state")
    thread_manager = infra.require("thread_manager", ThreadManager)
    theme = infra.require("theme_manager")

    assert config is not None
    assert state is not None
    assert isinstance(thread_manager, ThreadManager)
    assert theme is not None

    # Ensure shutdown is idempotent and stops the thread manager safely even if never started.
    infra.shutdown()
    assert thread_manager.shutdown.is_set()
    infra.shutdown()  # second call must be a no-op


def test_infrastructure_refreshable_tracking() -> None:
    app = object()
    infra = AppInfrastructure(app)
    widget = DummyWidget()
    other = DummyWidget()

    infra.register_refreshable(widget, fonts=True, theme=True)
    infra.register_refreshable(other, fonts=True, auto_detect=False)

    fonts = list(infra.iter_refreshables("fonts"))
    themes = list(infra.iter_refreshables("theme"))

    assert widget in fonts
    assert other in fonts
    assert widget in themes
    assert other not in themes
    other.destroy()
    fonts_after = list(infra.iter_refreshables("fonts"))
    assert widget in fonts_after
    assert other not in fonts_after

    infra.unregister_refreshable(widget)
    assert widget not in list(infra.iter_refreshables("fonts"))


def test_app_infrastructure_reports_modules() -> None:
    infra = AppInfrastructure(object())
    report = infra.diagnose()

    assert "core-services" in report.installed_modules
    assert report.module_dependencies["ui-services"] == ("core-services",)
    description = report.module_descriptions["core-services"]
    assert description is not None
    assert description.startswith("Registers core")


def test_app_infrastructure_supports_extra_modules() -> None:
    extra_module = ServiceModule(
        name="extra",
        dependencies=("core-services",),
        configure=lambda reg: reg.register_instance("extra-marker", {"active": True}),
    )

    infra = AppInfrastructure(object(), extra_modules=[extra_module])

    assert infra.registry.resolve("extra-marker") == {"active": True}
    assert "extra" in infra.registry.installed_modules()


def test_app_infrastructure_health_and_topology() -> None:
    infra = AppInfrastructure(object())

    snapshot = infra.health_snapshot()
    assert any(status.name == "config" for status in snapshot)
    assert infra.critical_services_healthy() is True

    infra.registry.register(
        "unstable_service",
        lambda reg: {"ready": False},
        health_check=lambda instance, reg: HealthCheckResult(False, "degraded"),
        critical=True,
    )

    assert infra.critical_services_healthy() is False

    topology = infra.service_topology()
    assert isinstance(topology, ServiceTopology)
    assert "unstable_service" in topology.activation_order

    report = infra.diagnose()
    assert report.service_health
    assert report.service_topology.activation_order == topology.activation_order
    assert report.critical_services_healthy is False

    infra.shutdown()
    post_report = infra.diagnose()
    assert post_report.service_health == ()


def test_view_store_registration() -> None:
    app = object()
    infra = AppInfrastructure(app)
    view1 = DummyWidget()
    view2 = DummyWidget()

    store = infra.create_view_store({"home": view1})
    store["tools"] = view2

    assert store["home"] is view1
    assert store["tools"] is view2

    fonts = list(infra.iter_refreshables("fonts"))
    assert view1 in fonts and view2 in fonts

    del store["home"]
    fonts = list(infra.iter_refreshables("fonts"))
    assert view1 not in fonts and view2 in fonts

    store.clear()
    assert list(store.keys()) == []
    assert list(infra.iter_refreshables("fonts")) == []


def test_iter_refreshables_unknown_kind() -> None:
    infra = AppInfrastructure(object())
    with pytest.raises(KeyError):
        list(infra.iter_refreshables("bogus"))


def test_auto_detect_refreshables_and_broadcast() -> None:
    infra = AppInfrastructure(object())
    widget = DummyWidget()

    infra.register_refreshable(widget)

    fonts = list(infra.iter_refreshables("fonts"))
    themes = list(infra.iter_refreshables("theme"))
    assert widget in fonts
    assert widget in themes

    infra.broadcast_refresh(fonts=True, theme=True)
    assert widget.fonts_refreshed == 1
    assert widget.theme_refreshed == 1


def test_app_infrastructure_resolution_insights_tracks_events() -> None:
    infra = AppInfrastructure(object(), slow_resolution_threshold=0.0)
    registry = infra.registry

    registry.register(
        "slow", lambda reg: "value", lifetime=ServiceLifetime.TRANSIENT, tags={"test"}
    )
    registry.resolve("slow")

    insights = infra.resolution_insights()
    assert insights.slow_services["slow"] >= 0.0

    def failing(_: ServiceRegistry) -> object:
        raise ValueError("broken service")

    registry.register("failing", failing, replace=True)
    with pytest.raises(ValueError):
        registry.resolve("failing")

    updated = infra.resolution_insights()
    assert updated.failure_counts["failing"] == 1
    last_failure = updated.last_failure_messages["failing"]
    assert last_failure is not None
    assert last_failure.endswith("broken service")
    assert updated.recovery_counts == {}

    report = infra.diagnose()
    assert report.resolution_observers >= 1
    assert report.resolution_history
    assert report.resolution_history[-1].success is False
    assert report.resolution_failures["failing"] == 1
    assert "slow" in report.slow_services
    assert report.recovery_counts == {}
    assert report.service_health
    assert isinstance(report.service_topology, ServiceTopology)
    assert isinstance(report.critical_services_healthy, bool)

    attempts = {"count": 0}
    retry_policy = ResiliencePolicy(max_attempts=2, retry_exceptions=(ValueError,))

    def eventually(_: ServiceRegistry) -> int:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("try again")
        return attempts["count"]

    registry.register("recovering", eventually, resilience=retry_policy)
    assert registry.resolve("recovering") == 2

    recovery_insights = infra.resolution_insights()
    assert recovery_insights.recovery_counts["recovering"] >= 1
    assert recovery_insights.failure_counts.get("recovering", 0) == 0

    second_report = infra.diagnose()
    assert second_report.recovery_counts["recovering"] >= 1
    resilience = second_report.service_resilience.get("recovering")
    assert resilience is not None
    assert resilience["max_attempts"] == 2

    infra.shutdown()
    post_shutdown = infra.diagnose()
    assert post_shutdown.resolution_observers == 0
    assert post_shutdown.recovery_counts == {}
    assert post_shutdown.service_health == ()


def test_infrastructure_diagnose_reports_health(monkeypatch) -> None:
    monkeypatch.setattr(infra_module.platform, "system", lambda: "Linux")
    infra = AppInfrastructure(object())
    widget = DummyWidget()
    infra.register_refreshable(widget, fonts=True, auto_detect=False)
    infra.create_view_store({})

    report = infra.diagnose()

    assert report.platform == "Linux"
    assert report.supports_admin_access is False
    assert set(report.registered_services) >= {"app", "config", "app_state", "thread_manager", "theme_manager"}
    assert report.missing_core_services == ()
    assert report.refreshable_counts["fonts"] == 1
    assert report.refreshable_counts["theme"] == 0
    assert report.shutdown is False
    assert report.aliases.get("theme") == "theme_manager"
    assert "ui" in report.active_scopes or any(scope.startswith("ui") for scope in report.active_scopes)
    assert "view-store" in report.scope_snapshots.get("ui", ()) or any(
        "view-store" in snapshot for name, snapshot in report.scope_snapshots.items() if name.startswith("ui")
    )
    assert report.core_service_status["thread_manager"] is True
    assert report.service_dependencies["theme_manager"] == ("config",)
    assert report.service_metrics["thread_manager"].failures == 0
    assert report.service_metrics["theme_manager"].contract_violations == 0
    assert report.resolution_observers >= 1
    assert report.resolution_history
    assert report.resolution_failures == {}
    assert isinstance(report.slow_services, dict)
    assert report.last_failure_messages == {}
    assert report.service_resilience["config"] is None
    assert report.recovery_counts == {}
    assert report.service_health
    assert report.critical_services_healthy is True
    assert isinstance(report.service_topology, ServiceTopology)
    assert report.service_topology.roots

    infra.shutdown()
    shutdown_report = infra.diagnose()
    assert shutdown_report.shutdown is True
    assert shutdown_report.resolution_observers == 0
    assert shutdown_report.service_health == ()


def test_macos_admin_support_announcement(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(infra_module.platform, "system", lambda: "Darwin")
    caplog.set_level(logging.INFO)

    AppInfrastructure(object())

    assert any(
        "Administrator access also works on macOS without an issue" in message
        for message in caplog.messages
    )


def test_supports_admin_access_flag(monkeypatch) -> None:
    monkeypatch.setattr(infra_module.platform, "system", lambda: "Darwin")
    infra = AppInfrastructure(object())
    assert infra.supports_admin_access() is True

    monkeypatch.setattr(infra_module.platform, "system", lambda: "Windows")
    infra_windows = AppInfrastructure(object())
    assert infra_windows.supports_admin_access() is False
