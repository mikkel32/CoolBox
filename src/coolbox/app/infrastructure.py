"""Infrastructure helpers wiring CoolBox services and UI registries.

The infrastructure is designed to be resilient across platforms. In particular,
administrator access flows are fully supported on macOS without requiring any
additional configuration or workarounds; administrator access also works on
macOS without an issue.  The module now organises service lifetimes, scoped
resources, and refresh tracking to make the application infrastructure smarter
and easier to reason about.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Callable,
    ContextManager,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    TypeVar,
)
import logging
import platform
import threading
import time
import weakref

from coolbox.config import Config
from coolbox.models.app_state import AppState
from coolbox.utils.thread_manager import ThreadManager
from coolbox.utils.theme import ThemeManager

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceLifetime(str, Enum):
    """Supported lifetimes for services tracked by :class:`ServiceRegistry`."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


@dataclass(slots=True)
class ServiceDescriptor:
    """Metadata associated with a registered service."""

    factory: Callable[["ServiceRegistry"], Any]
    tags: frozenset[str]
    lifetime: ServiceLifetime
    eager: bool
    on_close: Callable[[Any], None] | None
    aliases: tuple[str, ...]
    dependencies: tuple[str, ...]
    contract: type[Any] | tuple[type[Any], ...] | None
    validator: Callable[[Any, "ServiceRegistry"], None] | None
    resilience: ResiliencePolicy | None
    health_check: Callable[[Any, "ServiceRegistry"], Any] | None
    critical: bool


@dataclass(slots=True)
class ServiceRuntimeMetrics:
    """Runtime statistics captured for a service."""

    created: int = 0
    failures: int = 0
    last_error: str | None = None
    last_duration: float | None = None
    total_duration: float = 0.0
    contract_violations: int = 0
    last_created: float | None = None
    retries: int = 0
    fallback_uses: int = 0
    last_attempts: int = 0
    last_recovered: bool = False

    def copy(self) -> "ServiceRuntimeMetrics":
        return ServiceRuntimeMetrics(
            created=self.created,
            failures=self.failures,
            last_error=self.last_error,
            last_duration=self.last_duration,
            total_duration=self.total_duration,
            contract_violations=self.contract_violations,
            last_created=self.last_created,
            retries=self.retries,
            fallback_uses=self.fallback_uses,
            last_attempts=self.last_attempts,
            last_recovered=self.last_recovered,
        )


@dataclass(slots=True)
class ServiceResolutionEvent:
    """Snapshot describing a single service resolution attempt."""

    name: str
    lifetime: ServiceLifetime
    scope: str
    success: bool
    duration: float | None
    error: str | None
    timestamp: float
    from_cache: bool
    dependency_chain: tuple[str, ...]
    attempt: int
    max_attempts: int
    recovered: bool
    retry_scheduled: bool


@dataclass(slots=True)
class HealthCheckResult:
    """Result returned by a service health probe."""

    healthy: bool
    details: str | None = None
    duration: float | None = None

    @staticmethod
    def from_outcome(outcome: Any) -> "HealthCheckResult":
        """Normalise arbitrary *outcome* values into :class:`HealthCheckResult`."""

        if isinstance(outcome, HealthCheckResult):
            return outcome
        if outcome is None:
            return HealthCheckResult(True, None, None)
        if isinstance(outcome, bool):
            return HealthCheckResult(outcome, None, None)
        if isinstance(outcome, str):
            return HealthCheckResult(True, outcome or None, None)
        if isinstance(outcome, Mapping):
            raw_details = outcome.get("details") if isinstance(outcome, Mapping) else None
            try:
                duration_value = outcome.get("duration")
                duration = float(duration_value) if duration_value is not None else None
            except (TypeError, ValueError):
                duration = None
            raw_healthy = outcome.get("healthy", True)
            healthy = bool(raw_healthy)
            details = (
                raw_details
                if raw_details is None or isinstance(raw_details, str)
                else str(raw_details)
            )
            return HealthCheckResult(healthy, details, duration)
        if isinstance(outcome, (tuple, list)):
            items = list(outcome)
            if not items:
                return HealthCheckResult(True, None, None)
            if len(items) == 1:
                single = items[0]
                if isinstance(single, bool):
                    return HealthCheckResult(bool(single), None, None)
                if single is None:
                    return HealthCheckResult(True, None, None)
                return HealthCheckResult(True, str(single), None)
            healthy = bool(items[0])
            details_item = items[1]
            details = details_item if isinstance(details_item, str) else (
                None if details_item is None else str(details_item)
            )
            duration = None
            if len(items) > 2:
                try:
                    duration = float(items[2]) if items[2] is not None else None
                except (TypeError, ValueError):
                    duration = None
            return HealthCheckResult(healthy, details, duration)
        return HealthCheckResult(bool(outcome), None if outcome else str(outcome))


@dataclass(slots=True)
class ServiceHealthStatus:
    """Health summary for a single registered service."""

    name: str
    healthy: bool
    critical: bool
    details: str | None
    checked: bool
    timestamp: float
    resolve_duration: float | None
    check_duration: float | None
    source: str


@dataclass(slots=True)
class ServiceTopology:
    """Describes dependency relationships between registered services."""

    activation_order: tuple[str, ...]
    roots: tuple[str, ...]
    leaves: tuple[str, ...]
    orphans: tuple[str, ...]
    cycles: tuple[tuple[str, ...], ...]
    missing_dependencies: Mapping[str, tuple[str, ...]]


@dataclass(slots=True, frozen=True)
class ResiliencePolicy:
    """Describe retry and fallback behaviour for a service."""

    max_attempts: int = 1
    initial_delay: float = 0.0
    backoff_factor: float = 1.0
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,)
    fallback: Callable[["ServiceRegistry", Exception], Any] | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay < 0:
            raise ValueError("initial_delay cannot be negative")
        if self.backoff_factor < 0:
            raise ValueError("backoff_factor cannot be negative")
        if not isinstance(self.retry_exceptions, tuple):
            raise TypeError("retry_exceptions must be a tuple of exception types")
        if not self.retry_exceptions:
            object.__setattr__(self, "retry_exceptions", (Exception,))
        else:
            normalized: list[type[BaseException]] = []
            for exc_type in self.retry_exceptions:
                if not isinstance(exc_type, type) or not issubclass(exc_type, BaseException):
                    raise TypeError("retry_exceptions must contain exception types")
                if exc_type not in normalized:
                    normalized.append(exc_type)
            object.__setattr__(self, "retry_exceptions", tuple(normalized))

    def should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return any(isinstance(exc, exc_type) for exc_type in self.retry_exceptions)

    def compute_delay(self, attempt: int) -> float:
        if self.initial_delay <= 0:
            return 0.0
        exponent = max(0, attempt - 1)
        return self.initial_delay * (self.backoff_factor ** exponent)

    def describe(self) -> Mapping[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "initial_delay": self.initial_delay,
            "backoff_factor": self.backoff_factor,
            "retry_exceptions": tuple(exc.__name__ for exc in self.retry_exceptions),
            "has_fallback": self.fallback is not None,
        }


@dataclass(slots=True)
class ResolutionInsights:
    """Aggregated insight derived from resolution events."""

    slow_services: Mapping[str, float]
    failure_counts: Mapping[str, int]
    last_failure_messages: Mapping[str, str | None]
    recovery_counts: Mapping[str, int]


@dataclass(slots=True, frozen=True)
class ServiceModule:
    """Group of related service registrations installed together."""

    name: str
    configure: Callable[["ServiceRegistry"], None]
    dependencies: tuple[str, ...] = ()
    description: str | None = None

    def normalized_dependencies(self) -> tuple[str, ...]:
        deps = tuple(dict.fromkeys(dep for dep in self.dependencies if dep))
        return deps

class ServiceScope:
    """Represents a scope that caches scoped services and manual attachments."""

    def __init__(
        self,
        registry: "ServiceRegistry",
        *,
        name: str,
        parent: ServiceScope | None = None,
        _is_root: bool = False,
    ) -> None:
        self._registry = registry
        self._name = name
        self._parent = parent
        self._lock = threading.RLock()
        self._instances: dict[str, Any] = {}
        self._shutdown_callbacks: dict[str, tuple[Callable[[Any], None], Any]] = {}
        self._closed = False
        self._is_root = _is_root
        if not _is_root:
            registry._register_scope(self)

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def parent(self) -> ServiceScope | None:
        return self._parent

    def is_closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    def resolve(self, name: str) -> Any:
        self._ensure_open()
        return self._registry._resolve(name, self, ())

    def require(
        self,
        name: str,
        expected_type: type[T] | tuple[type[Any], ...] | None = None,
    ) -> T:
        instance = self.resolve(name)
        if expected_type is not None and not isinstance(instance, expected_type):
            raise TypeError(f"Scoped service '{name}' is not of type {expected_type!r}")
        return instance  # type: ignore[return-value]

    # ------------------------------------------------------------------
    def attach_instance(
        self,
        name: str,
        instance: Any,
        *,
        on_close: Callable[[Any], None] | None = None,
        replace: bool = False,
    ) -> None:
        """Attach an externally created instance to this scope."""

        self._ensure_open()
        self._registry._validate_service_name(name)
        previous_callback: tuple[Callable[[Any], None], Any] | None = None
        with self._lock:
            if name in self._instances and not replace:
                raise ValueError(f"Scope '{self._name}' already contains '{name}'")
            if replace:
                previous_callback = self._shutdown_callbacks.pop(name, None)
            self._instances[name] = instance
            if on_close is not None:
                self._shutdown_callbacks[name] = (on_close, instance)
            elif replace:
                self._shutdown_callbacks.pop(name, None)
        if previous_callback is not None:
            self._registry._invoke_shutdown_callback(name, previous_callback)

    def detach_instance(self, name: str, *, dispose: bool = True) -> None:
        self._ensure_open()
        callbacks = self._drop_service(name, dispose)
        for callback in callbacks:
            self._registry._invoke_shutdown_callback(name, callback)

    def get(self, name: str) -> Any:
        self._ensure_open()
        with self._lock:
            return self._instances[name]

    # ------------------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            callbacks = list(self._shutdown_callbacks.items())
            self._shutdown_callbacks.clear()
            self._instances.clear()
        for service_name, callback in callbacks:
            self._registry._invoke_shutdown_callback(service_name, callback)
        if not self._is_root:
            self._registry._release_scope(self)

    def snapshot(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._instances.keys()))

    # ------------------------------------------------------------------
    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"Scope '{self._name}' has been closed")

    def _get_cached_instance(self, name: str) -> Any:
        with self._lock:
            return self._instances.get(name, self._registry._MISSING)

    def _store_instance(
        self,
        name: str,
        instance: Any,
        on_close: Callable[[Any], None] | None,
    ) -> Any:
        with self._lock:
            cached = self._instances.get(name, self._registry._MISSING)
            if cached is not self._registry._MISSING:
                return cached
            self._instances[name] = instance
            if on_close is not None:
                self._shutdown_callbacks[name] = (on_close, instance)
        return instance

    def _drop_service(
        self,
        name: str,
        dispose: bool,
    ) -> list[tuple[Callable[[Any], None], Any]]:
        with self._lock:
            callback = self._shutdown_callbacks.pop(name, None)
            self._instances.pop(name, None)
        if dispose and callback is not None:
            return [callback]
        return []

    # ------------------------------------------------------------------
    def __enter__(self) -> "ServiceScope":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - no custom handling
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"ServiceScope(name={self._name!r}, closed={self._closed})"


class ServiceRegistry:
    """Lightweight dependency container for application services."""

    _MISSING: Any = object()

    def __init__(self) -> None:
        self._registry: dict[str, ServiceDescriptor] = {}
        self._singleton_cache: dict[str, Any] = {}
        self._singleton_shutdown_callbacks: dict[
            str, tuple[Callable[[Any], None], Any]
        ] = {}
        self._alias_map: dict[str, str] = {}
        self._shutdown = False
        self._lock = threading.RLock()
        self._scopes: weakref.WeakSet[ServiceScope] = weakref.WeakSet()
        self._scope_counter = 0
        self._root_scope = ServiceScope(self, name="root", _is_root=True)
        self._modules: dict[str, ServiceModule] = {}
        self._module_order: list[str] = []
        self._module_dependencies: dict[str, tuple[str, ...]] = {}
        self._module_descriptions: dict[str, str | None] = {}
        self._metrics: dict[str, ServiceRuntimeMetrics] = {}
        self._resolution_history: deque[ServiceResolutionEvent] = deque(maxlen=256)
        self._resolution_observers: list[Callable[[ServiceResolutionEvent], None]] = []
        self._default_resilience_policy: ResiliencePolicy | None = None

    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        factory: Callable[["ServiceRegistry"], Any],
        *,
        tags: Iterable[str] | None = None,
        lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
        eager: bool = False,
        on_close: Callable[[Any], None] | None = None,
        replace: bool = False,
        aliases: Iterable[str] | None = None,
        dependencies: Iterable[str] | None = None,
        contract: type[Any] | tuple[type[Any], ...] | None = None,
        validator: Callable[[Any, "ServiceRegistry"], None] | None = None,
        resilience: ResiliencePolicy | None = None,
        health_check: Callable[[Any, "ServiceRegistry"], Any] | None = None,
        critical: bool = False,
    ) -> None:
        """Register a service *name* backed by *factory*."""

        self._ensure_active()
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._validate_service_name(name)
        alias_tuple = tuple(dict.fromkeys(aliases or ()))
        for alias in alias_tuple:
            self._validate_service_name(alias)
            if alias == name:
                raise ValueError("Alias must be different from service name")
        sanitized_dependencies: list[str] = []
        for dependency in dependencies or ():
            if not isinstance(dependency, str):
                raise TypeError("dependencies must be provided as strings")
            candidate = dependency.strip()
            if candidate:
                sanitized_dependencies.append(candidate)
        dependency_tuple = tuple(dict.fromkeys(sanitized_dependencies))
        if name in dependency_tuple or any(alias in dependency_tuple for alias in alias_tuple):
            raise ValueError("Service cannot declare itself or its aliases as dependencies")
        if contract is not None and not self._is_valid_contract(contract):
            raise TypeError("contract must be a type or tuple of types")
        if validator is not None and not callable(validator):
            raise TypeError("validator must be callable")
        if resilience is not None and not isinstance(resilience, ResiliencePolicy):
            raise TypeError("resilience must be a ResiliencePolicy instance")
        if health_check is not None and not callable(health_check):
            raise TypeError("health_check must be callable")

        previous_descriptor: ServiceDescriptor | None = None
        previous_singleton_callback: tuple[Callable[[Any], None], Any] | None = None
        previous_instance: Any = self._MISSING
        with self._lock:
            effective_resilience = resilience or self._default_resilience_policy
            descriptor = ServiceDescriptor(
                factory=factory,
                tags=frozenset(tags or ()),
                lifetime=lifetime,
                eager=eager,
                on_close=on_close,
                aliases=alias_tuple,
                dependencies=dependency_tuple,
                contract=contract,
                validator=validator,
                resilience=effective_resilience,
                health_check=health_check,
                critical=bool(critical),
            )
            if not replace and name in self._registry:
                raise ValueError(f"Service '{name}' already registered")
            if name in self._alias_map:
                raise ValueError(f"Service name '{name}' is reserved as an alias")
            if replace and name in self._registry:
                previous_descriptor = self._registry.pop(name)
                previous_singleton_callback = self._singleton_shutdown_callbacks.pop(name, None)
                previous_instance = self._singleton_cache.pop(name, self._MISSING)
                self._metrics.pop(name, None)
                for alias, target in list(self._alias_map.items()):
                    if target == name:
                        self._alias_map.pop(alias)
            for alias in alias_tuple:
                if alias in self._registry or alias in self._alias_map:
                    raise ValueError(f"Alias '{alias}' is already registered")
            self._registry[name] = descriptor
            for alias in alias_tuple:
                self._alias_map[alias] = name
            self._metrics.setdefault(name, ServiceRuntimeMetrics())

        if previous_descriptor is not None:
            callbacks: list[tuple[Callable[[Any], None], Any]] = []
            if previous_descriptor.lifetime is ServiceLifetime.SINGLETON:
                if previous_singleton_callback is not None and previous_instance is not self._MISSING:
                    callbacks.append(previous_singleton_callback)
            elif previous_descriptor.lifetime is ServiceLifetime.SCOPED:
                callbacks.extend(self._purge_scoped_instances(name, dispose=True))
            for callback in callbacks:
                self._invoke_shutdown_callback(name, callback)

        if descriptor.eager:
            self.resolve(name)

    def register_instance(
        self,
        name: str,
        instance: Any,
        *,
        tags: Iterable[str] | None = None,
        on_close: Callable[[Any], None] | None = None,
        replace: bool = False,
        aliases: Iterable[str] | None = None,
        contract: type[Any] | tuple[type[Any], ...] | None = None,
        validator: Callable[[Any, "ServiceRegistry"], None] | None = None,
        resilience: ResiliencePolicy | None = None,
        health_check: Callable[[Any, "ServiceRegistry"], Any] | None = None,
        critical: bool = False,
    ) -> None:
        """Register a pre-created *instance* under *name*."""

        self._ensure_active()
        if contract is not None and not self._is_valid_contract(contract):
            raise TypeError("contract must be a type or tuple of types")
        if contract is not None and not isinstance(instance, contract):
            raise TypeError(
                f"Instance for service '{name}' does not match contract {contract!r}"
            )
        if validator is not None:
            if not callable(validator):
                raise TypeError("validator must be callable")
            validator(instance, self)

        def _factory(_: ServiceRegistry) -> Any:
            return instance

        self.register(
            name,
            _factory,
            tags=tags,
            lifetime=ServiceLifetime.SINGLETON,
            eager=True,
            on_close=on_close,
            replace=replace,
            aliases=aliases,
            contract=contract,
            validator=validator,
            resilience=resilience,
            health_check=health_check,
            critical=critical,
        )

        with self._lock:
            self._singleton_cache[name] = instance
            if on_close is not None:
                self._singleton_shutdown_callbacks[name] = (on_close, instance)

    def set_default_resilience_policy(self, policy: ResiliencePolicy | None) -> None:
        if policy is not None and not isinstance(policy, ResiliencePolicy):
            raise TypeError("policy must be a ResiliencePolicy instance or None")
        with self._lock:
            self._default_resilience_policy = policy

    def default_resilience_policy(self) -> ResiliencePolicy | None:
        with self._lock:
            return self._default_resilience_policy

    # ------------------------------------------------------------------
    def resolve(self, name: str, *, scope: ServiceScope | None = None) -> Any:
        scope = scope or self._root_scope
        return self._resolve(name, scope, ())

    def _resolve(
        self,
        name: str,
        scope: ServiceScope,
        stack: tuple[str, ...],
    ) -> Any:
        self._ensure_active()
        canonical_name = self._canonical_name(name)
        if canonical_name in stack:
            cycle = " -> ".join((*stack, canonical_name))
            raise RuntimeError(f"Cyclic service dependency detected: {cycle}")
        cached_instance: Any = self._MISSING
        with self._lock:
            try:
                descriptor = self._registry[canonical_name]
            except KeyError as exc:
                raise KeyError(f"Service '{name}' is not registered") from exc
            metrics = self._metrics.setdefault(canonical_name, ServiceRuntimeMetrics())
            lifetime = descriptor.lifetime
            if lifetime is ServiceLifetime.SINGLETON:
                cached_instance = self._singleton_cache.get(canonical_name, self._MISSING)
            elif lifetime is ServiceLifetime.SCOPED:
                cached_instance = scope._get_cached_instance(canonical_name)

        dependency_chain = (*stack, canonical_name)
        policy = descriptor.resilience
        max_attempts = policy.max_attempts if policy is not None else 1
        if cached_instance is not self._MISSING:
            cached_event = self._make_resolution_event(
                canonical_name,
                descriptor,
                scope,
                success=True,
                duration=0.0,
                error=None,
                from_cache=True,
                dependency_chain=dependency_chain,
                attempt=1,
                max_attempts=max_attempts,
                recovered=False,
                retry_scheduled=False,
            )
            self._emit_resolution_event(cached_event)
            return cached_instance

        attempts = 0
        used_fallback = False
        created: Any = self._MISSING
        attempt_duration: float = 0.0
        last_attempt_start: float = 0.0
        while True:
            attempts += 1
            attempt_start = time.perf_counter()
            last_attempt_start = attempt_start
            failure: Exception | None = None
            error_message: str | None = None
            last_dependency: str | None = None
            try:
                for dependency in descriptor.dependencies:
                    last_dependency = dependency
                    self._resolve(dependency, scope, dependency_chain)
            except Exception as exc:
                message = (
                    f"Dependency '{last_dependency}' failed while resolving '{canonical_name}': {exc}"
                    if last_dependency
                    else f"Dependency failure while resolving '{canonical_name}': {exc}"
                )
                failure = RuntimeError(message)
                error_message = message
            if failure is None:
                try:
                    candidate = descriptor.factory(self)
                except Exception as exc:
                    failure = exc
                    error_message = f"{type(exc).__name__}: {exc}"
                else:
                    created = candidate
                    attempt_duration = time.perf_counter() - attempt_start
                    break
            attempt_duration = time.perf_counter() - attempt_start
            assert error_message is not None
            if policy is not None and policy.should_retry(failure, attempts):
                self._record_retry(metrics, failure, attempts, attempt_duration)
                retry_event = self._make_resolution_event(
                    canonical_name,
                    descriptor,
                    scope,
                    success=False,
                    duration=attempt_duration,
                    error=error_message,
                    from_cache=False,
                    dependency_chain=dependency_chain,
                    attempt=attempts,
                    max_attempts=max_attempts,
                    recovered=False,
                    retry_scheduled=True,
                )
                self._emit_resolution_event(retry_event)
                delay = policy.compute_delay(attempts)
                if delay > 0:
                    time.sleep(delay)
                continue
            if policy is not None and policy.fallback is not None:
                try:
                    candidate = policy.fallback(self, failure)
                except Exception as fallback_exc:
                    fallback_message = (
                        f"Fallback for service '{canonical_name}' failed: "
                        f"{type(fallback_exc).__name__}: {fallback_exc}"
                    )
                    self._record_failure(metrics, fallback_exc, attempts)
                    failure_event = self._make_resolution_event(
                        canonical_name,
                        descriptor,
                        scope,
                        success=False,
                        duration=attempt_duration,
                        error=fallback_message,
                        from_cache=False,
                        dependency_chain=dependency_chain,
                        attempt=attempts,
                        max_attempts=max_attempts,
                        recovered=False,
                        retry_scheduled=False,
                    )
                    self._emit_resolution_event(failure_event)
                    raise
                else:
                    created = candidate
                    used_fallback = True
                    attempt_duration = time.perf_counter() - attempt_start
                    break
            self._record_failure(metrics, failure, attempts)
            failure_event = self._make_resolution_event(
                canonical_name,
                descriptor,
                scope,
                success=False,
                duration=attempt_duration,
                error=error_message,
                from_cache=False,
                dependency_chain=dependency_chain,
                attempt=attempts,
                max_attempts=max_attempts,
                recovered=False,
                retry_scheduled=False,
            )
            self._emit_resolution_event(failure_event)
            raise failure

        recovered = used_fallback or attempts > 1
        if used_fallback:
            self._record_fallback(metrics)
        duration = attempt_duration

        contract = descriptor.contract
        if contract is not None and not isinstance(created, contract):
            message = (
                f"Service '{canonical_name}' returned {type(created).__name__}"
                f" which does not satisfy contract {contract!r}"
            )
            self._record_contract_violation(metrics, message, attempts)
            failure_event = self._make_resolution_event(
                canonical_name,
                descriptor,
                scope,
                success=False,
                duration=duration,
                error=message,
                from_cache=False,
                dependency_chain=dependency_chain,
                attempt=attempts,
                max_attempts=max_attempts,
                recovered=False,
                retry_scheduled=False,
            )
            self._emit_resolution_event(failure_event)
            raise TypeError(message)

        if descriptor.validator is not None:
            try:
                descriptor.validator(created, self)
            except Exception as exc:
                validation_duration = time.perf_counter() - last_attempt_start
                self._record_failure(metrics, exc, attempts)
                message = f"{type(exc).__name__}: {exc}"
                failure_event = self._make_resolution_event(
                    canonical_name,
                    descriptor,
                    scope,
                    success=False,
                    duration=validation_duration,
                    error=message,
                    from_cache=False,
                    dependency_chain=dependency_chain,
                    attempt=attempts,
                    max_attempts=max_attempts,
                    recovered=False,
                    retry_scheduled=False,
                )
                self._emit_resolution_event(failure_event)
                raise

        duration = max(duration, time.perf_counter() - last_attempt_start)
        self._record_success(metrics, duration, attempts, recovered)

        if lifetime is ServiceLifetime.TRANSIENT:
            if descriptor.on_close is not None:
                logger.debug(
                    "Transient service %s supplied shutdown callback; it will not be invoked automatically.",
                    canonical_name,
                )
            success_event = self._make_resolution_event(
                canonical_name,
                descriptor,
                scope,
                success=True,
                duration=duration,
                error=None,
                from_cache=False,
                dependency_chain=dependency_chain,
                attempt=attempts,
                max_attempts=max_attempts,
                recovered=recovered,
                retry_scheduled=False,
            )
            self._emit_resolution_event(success_event)
            return created

        if lifetime is ServiceLifetime.SINGLETON:
            with self._lock:
                existing = self._singleton_cache.get(canonical_name, self._MISSING)
                if existing is self._MISSING:
                    self._singleton_cache[canonical_name] = created
                    if descriptor.on_close is not None:
                        self._singleton_shutdown_callbacks[canonical_name] = (
                            descriptor.on_close,
                            created,
                        )
                    instance = created
                    from_cache = False
                else:
                    instance = existing
                    from_cache = True
            success_event = self._make_resolution_event(
                canonical_name,
                descriptor,
                scope,
                success=True,
                duration=duration,
                error=None,
                from_cache=from_cache,
                dependency_chain=dependency_chain,
                attempt=attempts,
                max_attempts=max_attempts,
                recovered=recovered,
                retry_scheduled=False,
            )
            self._emit_resolution_event(success_event)
            return instance

        stored = scope._store_instance(canonical_name, created, descriptor.on_close)
        from_cache = stored is not created
        success_event = self._make_resolution_event(
            canonical_name,
            descriptor,
            scope,
            success=True,
            duration=duration,
            error=None,
            from_cache=from_cache,
            dependency_chain=dependency_chain,
            attempt=attempts,
            max_attempts=max_attempts,
            recovered=recovered,
            retry_scheduled=False,
        )
        self._emit_resolution_event(success_event)
        return stored

    def require(self, name: str, expected_type: type[T] | tuple[type[Any], ...] | None = None) -> T:
        instance = self.resolve(name)
        if expected_type is not None and not isinstance(instance, expected_type):
            raise TypeError(f"Service '{name}' is not of type {expected_type!r}")
        return instance  # type: ignore[return-value]

    # ------------------------------------------------------------------
    def add_resolution_observer(
        self, observer: Callable[[ServiceResolutionEvent], None]
    ) -> None:
        """Register *observer* to receive resolution events."""

        self._ensure_active()
        if not callable(observer):
            raise TypeError("observer must be callable")
        with self._lock:
            if observer in self._resolution_observers:
                raise ValueError("observer already registered")
            self._resolution_observers.append(observer)

    def remove_resolution_observer(
        self, observer: Callable[[ServiceResolutionEvent], None]
    ) -> None:
        with self._lock:
            try:
                self._resolution_observers.remove(observer)
            except ValueError as exc:
                raise KeyError("observer not registered") from exc

    def resolution_observer_count(self) -> int:
        with self._lock:
            return len(self._resolution_observers)

    def resolution_history(self) -> tuple[ServiceResolutionEvent, ...]:
        with self._lock:
            return tuple(self._resolution_history)

    def clear_resolution_history(self) -> None:
        with self._lock:
            self._resolution_history.clear()

    # ------------------------------------------------------------------
    def services_with_tag(self, tag: str) -> list[str]:
        self._ensure_active()
        with self._lock:
            return [name for name, descriptor in self._registry.items() if tag in descriptor.tags]

    def unregister(self, name: str, *, dispose: bool = True) -> None:
        self._ensure_active()
        callbacks: list[tuple[Callable[[Any], None], Any]] = []
        with self._lock:
            canonical_name = self._canonical_name(name)
            descriptor = self._registry.pop(canonical_name, None)
            if descriptor is None:
                raise KeyError(f"Service '{name}' is not registered")
            for alias, target in list(self._alias_map.items()):
                if target == canonical_name:
                    self._alias_map.pop(alias)
            singleton_callback = self._singleton_shutdown_callbacks.pop(canonical_name, None)
            instance = self._singleton_cache.pop(canonical_name, self._MISSING)
            self._metrics.pop(canonical_name, None)
        if dispose:
            if singleton_callback is not None and instance is not self._MISSING:
                callbacks.append(singleton_callback)
            if descriptor.lifetime is ServiceLifetime.SCOPED:
                callbacks.extend(self._purge_scoped_instances(canonical_name, dispose=True))
        for callback in callbacks:
            self._invoke_shutdown_callback(canonical_name, callback)

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            callbacks = list(self._singleton_shutdown_callbacks.items())
            self._singleton_shutdown_callbacks.clear()
            self._singleton_cache.clear()
            descriptors = dict(self._registry)
            self._registry.clear()
            scopes = list(self._scopes)
            self._metrics.clear()
            self._resolution_observers.clear()
        for scope in scopes:
            scope.close()
        self._root_scope.close()
        for name, callback in callbacks:
            self._invoke_shutdown_callback(name, callback)
        # Dispose scoped services captured before registry clear
        for name, descriptor in descriptors.items():
            if descriptor.lifetime is ServiceLifetime.SCOPED:
                scoped_callbacks = self._purge_scoped_instances(name, dispose=True)
                for callback in scoped_callbacks:
                    self._invoke_shutdown_callback(name, callback)

    # ------------------------------------------------------------------
    def is_registered(self, name: str) -> bool:
        with self._lock:
            canonical = self._alias_map.get(name, name)
            return canonical in self._registry

    def registered_services(self) -> list[str]:
        with self._lock:
            return sorted(self._registry.keys())

    def service_dependencies(self) -> Mapping[str, tuple[str, ...]]:
        with self._lock:
            return {
                name: descriptor.dependencies
                for name, descriptor in self._registry.items()
            }

    def service_metrics(self) -> Mapping[str, ServiceRuntimeMetrics]:
        with self._lock:
            return {
                name: metrics.copy()
                for name, metrics in self._metrics.items()
            }

    def service_resilience_policies(self) -> Mapping[str, Mapping[str, Any] | None]:
        with self._lock:
            return {
                name: (
                    descriptor.resilience.describe()
                    if descriptor.resilience is not None
                    else None
                )
                for name, descriptor in self._registry.items()
            }

    def check_health(
        self,
        name: str,
        *,
        scope: ServiceScope | None = None,
        tolerate_failures: bool = False,
    ) -> ServiceHealthStatus:
        scope = scope or self._root_scope
        with self._lock:
            if self._shutdown:
                if tolerate_failures:
                    return ServiceHealthStatus(
                        name=name,
                        healthy=False,
                        critical=False,
                        details="Service registry is shutdown",
                        checked=False,
                        timestamp=time.time(),
                        resolve_duration=None,
                        check_duration=None,
                        source="registry",
                    )
                raise RuntimeError("Service registry is shutdown")
            canonical = self._alias_map.get(name, name)
            descriptor = self._registry.get(canonical)
            if descriptor is None:
                raise KeyError(f"Service '{name}' is not registered")
        resolve_start = time.perf_counter()
        try:
            instance = self._resolve(canonical, scope, ())
        except Exception as exc:
            resolve_duration = time.perf_counter() - resolve_start
            details = f"Resolution failed: {type(exc).__name__}: {exc}"
            if not tolerate_failures:
                raise
            return ServiceHealthStatus(
                name=canonical,
                healthy=False,
                critical=descriptor.critical,
                details=details,
                checked=False,
                timestamp=time.time(),
                resolve_duration=resolve_duration,
                check_duration=None,
                source="resolution",
            )
        resolve_duration = time.perf_counter() - resolve_start
        details: str | None = None
        check_duration: float | None = None
        healthy = True
        checked = False
        source = "resolution"
        if descriptor.health_check is not None:
            checked = True
            check_start = time.perf_counter()
            try:
                outcome = descriptor.health_check(instance, self)
            except Exception as exc:
                check_duration = time.perf_counter() - check_start
                details = f"Health check failed: {type(exc).__name__}: {exc}"
                healthy = False
            else:
                result = HealthCheckResult.from_outcome(outcome)
                measured_duration = time.perf_counter() - check_start
                check_duration = result.duration if result.duration is not None else measured_duration
                healthy = bool(result.healthy)
                details = result.details
                source = "health_check"
        return ServiceHealthStatus(
            name=canonical,
            healthy=healthy,
            critical=descriptor.critical,
            details=details,
            checked=checked,
            timestamp=time.time(),
            resolve_duration=resolve_duration,
            check_duration=check_duration,
            source=source,
        )

    def health_snapshot(
        self,
        *,
        scope: ServiceScope | None = None,
        tolerate_failures: bool = True,
    ) -> tuple[ServiceHealthStatus, ...]:
        with self._lock:
            if self._shutdown:
                return ()
            names = tuple(self._registry.keys())
        statuses: list[ServiceHealthStatus] = []
        for service_name in names:
            try:
                status = self.check_health(
                    service_name,
                    scope=scope,
                    tolerate_failures=tolerate_failures,
                )
            except Exception as exc:
                if not tolerate_failures:
                    raise
                with self._lock:
                    descriptor = self._registry.get(service_name)
                critical = descriptor.critical if descriptor is not None else False
                statuses.append(
                    ServiceHealthStatus(
                        name=service_name,
                        healthy=False,
                        critical=critical,
                        details=f"Health snapshot failed: {type(exc).__name__}: {exc}",
                        checked=False,
                        timestamp=time.time(),
                        resolve_duration=None,
                        check_duration=None,
                        source="health_snapshot",
                    )
                )
            else:
                statuses.append(status)
        return tuple(statuses)

    def service_topology(self) -> ServiceTopology:
        with self._lock:
            if self._shutdown and not self._registry:
                return ServiceTopology(
                    activation_order=(),
                    roots=(),
                    leaves=(),
                    orphans=(),
                    cycles=(),
                    missing_dependencies={},
                )
            descriptors = dict(self._registry)
            alias_map = dict(self._alias_map)
        if not descriptors:
            return ServiceTopology(
                activation_order=(),
                roots=(),
                leaves=(),
                orphans=(),
                cycles=(),
                missing_dependencies={},
            )
        graph: dict[str, tuple[str, ...]] = {}
        dependents: dict[str, set[str]] = {name: set() for name in descriptors}
        missing: dict[str, list[str]] = {}
        for name, descriptor in descriptors.items():
            resolved: list[str] = []
            for dependency in descriptor.dependencies:
                target = alias_map.get(dependency, dependency)
                if target in descriptors:
                    if target not in resolved:
                        resolved.append(target)
                    dependents.setdefault(target, set()).add(name)
                else:
                    missing.setdefault(name, []).append(dependency)
            graph[name] = tuple(resolved)
            dependents.setdefault(name, dependents.get(name, set()))

        order: list[str] = []
        temp: set[str] = set()
        perm: set[str] = set()
        cycles: list[tuple[str, ...]] = []
        seen_cycles: set[frozenset[str]] = set()

        def dfs(node: str, stack: list[str]) -> None:
            if node in perm:
                return
            temp.add(node)
            stack.append(node)
            for dependency in graph.get(node, ()):  # dependencies resolved first
                if dependency in temp:
                    if dependency in stack:
                        idx = stack.index(dependency)
                        cycle = tuple((*stack[idx:], dependency))
                        key = frozenset(cycle)
                        if key not in seen_cycles:
                            seen_cycles.add(key)
                            cycles.append(cycle)
                    continue
                if dependency not in descriptors:
                    continue
                dfs(dependency, stack)
            temp.discard(node)
            stack.pop()
            perm.add(node)
            if node not in order:
                order.append(node)

        for service_name in sorted(graph):
            if service_name not in perm:
                dfs(service_name, [])

        roots = tuple(sorted(name for name, deps in graph.items() if not deps))
        leaves = tuple(
            sorted(name for name, dependents_set in dependents.items() if not dependents_set)
        )
        orphans = tuple(sorted(name for name in roots if not dependents.get(name)))
        missing_map = {name: tuple(sorted(values)) for name, values in missing.items()}

        return ServiceTopology(
            activation_order=tuple(order),
            roots=roots,
            leaves=leaves,
            orphans=orphans,
            cycles=tuple(cycles),
            missing_dependencies=missing_map,
        )

    def install_module(self, module: ServiceModule, *, replace: bool = False) -> None:
        """Install a :class:`ServiceModule` after validating dependencies."""

        self._ensure_active()
        name = (module.name or "").strip()
        if not name:
            raise ValueError("Module name must be a non-empty string")
        dependencies = module.normalized_dependencies()
        with self._lock:
            missing = [dependency for dependency in dependencies if dependency not in self._modules]
            if missing:
                missing_display = ", ".join(sorted(missing))
                raise RuntimeError(
                    f"Module '{name}' has unmet dependencies: {missing_display}"
                )
            installed = name in self._modules
            if installed and not replace:
                raise ValueError(f"Module '{name}' is already installed")
            previous_index = self._module_order.index(name) if installed else None
        try:
            module.configure(self)
        except Exception:
            logger.exception("Module '%s' failed during installation", name)
            raise
        with self._lock:
            self._modules[name] = module
            self._module_dependencies[name] = dependencies
            self._module_descriptions[name] = module.description
            if previous_index is not None:
                self._module_order[previous_index] = name
            else:
                self._module_order.append(name)

    def installed_modules(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._module_order)

    def module_dependencies(self) -> Mapping[str, tuple[str, ...]]:
        with self._lock:
            return {
                name: self._module_dependencies.get(name, ())
                for name in self._module_order
            }

    def module_descriptions(self) -> Mapping[str, str | None]:
        with self._lock:
            return {
                name: self._module_descriptions.get(name)
                for name in self._module_order
            }

    def is_module_installed(self, name: str) -> bool:
        with self._lock:
            return name in self._modules

    def alias_map(self) -> Mapping[str, str]:
        with self._lock:
            return dict(self._alias_map)

    def tags_index(self) -> Mapping[str, tuple[str, ...]]:
        with self._lock:
            tag_map: dict[str, set[str]] = {}
            for name, descriptor in self._registry.items():
                for tag in descriptor.tags:
                    tag_map.setdefault(tag, set()).add(name)
        return {tag: tuple(sorted(names)) for tag, names in tag_map.items()}

    def active_scopes(self) -> tuple[str, ...]:
        names: list[str] = []
        if not self._root_scope.is_closed():
            names.append(self._root_scope.name)
        with self._lock:
            names.extend(scope.name for scope in self._scopes if not scope.is_closed())
        return tuple(sorted(dict.fromkeys(names)))

    def scope_snapshots(self) -> Mapping[str, tuple[str, ...]]:
        snapshots: dict[str, tuple[str, ...]] = {self._root_scope.name: self._root_scope.snapshot()}
        with self._lock:
            scopes = list(self._scopes)
        for scope in scopes:
            snapshots[scope.name] = scope.snapshot()
        return snapshots

    def create_scope(
        self,
        name: str | None = None,
        *,
        parent: ServiceScope | None = None,
    ) -> ServiceScope:
        self._ensure_active()
        scope_name = self._make_scope_name(name)
        return ServiceScope(self, name=scope_name, parent=parent or self._root_scope)

    # ------------------------------------------------------------------
    def _make_scope_name(self, name: str | None) -> str:
        base = (name or "scope").strip() or "scope"
        if base == "root":
            base = "scope"
        with self._lock:
            existing = {self._root_scope.name, *[scope.name for scope in self._scopes]}
            candidate = base
            counter = 1
            while candidate in existing:
                candidate = f"{base}-{counter}"
                counter += 1
            self._scope_counter += 1
            return candidate

    def _canonical_name(self, name: str) -> str:
        with self._lock:
            canonical = self._alias_map.get(name, name)
            if canonical in self._registry:
                return canonical
        raise KeyError(name)

    def _register_scope(self, scope: ServiceScope) -> None:
        with self._lock:
            self._scopes.add(scope)

    def _release_scope(self, scope: ServiceScope) -> None:
        with self._lock:
            self._scopes.discard(scope)

    def _purge_scoped_instances(
        self,
        name: str,
        *,
        dispose: bool,
    ) -> list[tuple[Callable[[Any], None], Any]]:
        callbacks: list[tuple[Callable[[Any], None], Any]] = []
        with self._lock:
            scopes = list(self._scopes)
        for scope in scopes:
            callbacks.extend(scope._drop_service(name, dispose))
        callbacks.extend(self._root_scope._drop_service(name, dispose))
        return callbacks

    @staticmethod
    def _validate_service_name(name: str) -> None:
        if not name or not name.strip():
            raise ValueError("Service name must be a non-empty string")

    @staticmethod
    def _invoke_shutdown_callback(
        name: str,
        callback_info: tuple[Callable[[Any], None], Any],
    ) -> None:
        callback, instance = callback_info
        try:
            callback(instance)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Shutdown callback for %s failed", name)

    def _ensure_active(self) -> None:
        if self._shutdown:
            raise RuntimeError("ServiceRegistry has been shut down")

    @staticmethod
    def _is_valid_contract(contract: type[Any] | tuple[type[Any], ...]) -> bool:
        if isinstance(contract, type):
            return True
        if isinstance(contract, tuple) and contract and all(
            isinstance(entry, type) for entry in contract
        ):
            return True
        return False

    def _record_success(
        self,
        metrics: ServiceRuntimeMetrics,
        duration: float,
        attempts: int,
        recovered: bool,
    ) -> None:
        with self._lock:
            metrics.created += 1
            metrics.last_duration = duration
            metrics.total_duration += duration
            metrics.last_created = time.time()
            metrics.last_error = None
            metrics.last_attempts = attempts
            metrics.last_recovered = recovered

    def _record_failure(
        self,
        metrics: ServiceRuntimeMetrics,
        exc: Exception,
        attempts: int,
    ) -> None:
        message = f"{type(exc).__name__}: {exc}"
        with self._lock:
            metrics.failures += 1
            metrics.last_error = message
            metrics.last_duration = None
            metrics.last_attempts = attempts
            metrics.last_recovered = False

    def _record_retry(
        self,
        metrics: ServiceRuntimeMetrics,
        exc: Exception,
        attempts: int,
        duration: float,
    ) -> None:
        message = f"{type(exc).__name__}: {exc}"
        with self._lock:
            metrics.retries += 1
            metrics.last_error = message
            metrics.last_duration = duration
            metrics.last_attempts = attempts
            metrics.last_recovered = False

    def _record_fallback(self, metrics: ServiceRuntimeMetrics) -> None:
        with self._lock:
            metrics.fallback_uses += 1

    def _record_contract_violation(
        self,
        metrics: ServiceRuntimeMetrics,
        message: str,
        attempts: int,
    ) -> None:
        with self._lock:
            metrics.contract_violations += 1
            metrics.failures += 1
            metrics.last_error = message
            metrics.last_duration = None
            metrics.last_attempts = attempts
            metrics.last_recovered = False

    def _make_resolution_event(
        self,
        name: str,
        descriptor: ServiceDescriptor,
        scope: ServiceScope,
        *,
        success: bool,
        duration: float | None,
        error: str | None,
        from_cache: bool,
        dependency_chain: tuple[str, ...],
        attempt: int,
        max_attempts: int,
        recovered: bool,
        retry_scheduled: bool,
    ) -> ServiceResolutionEvent:
        return ServiceResolutionEvent(
            name=name,
            lifetime=descriptor.lifetime,
            scope=scope.name,
            success=success,
            duration=duration,
            error=error,
            timestamp=time.time(),
            from_cache=from_cache,
            dependency_chain=dependency_chain,
            attempt=attempt,
            max_attempts=max_attempts,
            recovered=recovered,
            retry_scheduled=retry_scheduled,
        )

    def _emit_resolution_event(self, event: ServiceResolutionEvent) -> None:
        with self._lock:
            self._resolution_history.append(event)
            observers = tuple(self._resolution_observers)
        for observer in observers:
            try:
                observer(event)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Resolution observer failed for %s", event.name)


class _RefreshableStore:
    """Track widgets requiring refresh notifications."""

    def __init__(self) -> None:
        self._items: dict[int, weakref.ReferenceType[Any] | Any] = {}
        self._lock = threading.RLock()

    def add(self, obj: Any) -> None:
        if obj is None:
            return
        ident = id(obj)
        with self._lock:
            if ident in self._items:
                return
            try:
                self._items[ident] = weakref.ref(obj, lambda _: self._remove_by_id(ident))
            except TypeError:
                self._items[ident] = obj

    def remove(self, obj: Any) -> None:
        if obj is None:
            return
        self._remove_by_id(id(obj))

    def _remove_by_id(self, ident: int) -> None:
        with self._lock:
            self._items.pop(ident, None)

    def iter_alive(self) -> Iterator[Any]:
        with self._lock:
            snapshot = list(self._items.items())
        for ident, stored in snapshot:
            obj = stored() if isinstance(stored, weakref.ReferenceType) else stored
            if obj is None or not self._is_alive(obj):
                self._remove_by_id(ident)
                continue
            yield obj

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    @staticmethod
    def _is_alive(obj: Any) -> bool:
        if obj is None:
            return False
        exists_fn = getattr(obj, "winfo_exists", None)
        if callable(exists_fn):
            try:
                return bool(exists_fn())
            except Exception:  # pragma: no cover - defensive
                return False
        return True


class ViewStore(MutableMapping[str, Any]):
    """Mapping that auto-registers views for refresh notifications."""

    def __init__(
        self,
        infrastructure: "AppInfrastructure",
        initial: Mapping[str, Any] | None = None,
    ) -> None:
        self._infra = infrastructure
        self._store: dict[str, Any] = {}
        if initial:
            self.update(initial)

    def __getitem__(self, key: str) -> Any:
        return self._store[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._store[key] = value
        self._infra.register_refreshable(value, fonts=True, theme=True)

    def __delitem__(self, key: str) -> None:
        value = self._store.pop(key)
        self._infra.unregister_refreshable(value)

    def __iter__(self) -> Iterator[str]:
        return iter(self._store)

    def __len__(self) -> int:
        return len(self._store)

    def clear(self) -> None:  # type: ignore[override]
        for value in list(self._store.values()):
            self._infra.unregister_refreshable(value)
        self._store.clear()


@dataclass(slots=True)
class InfrastructureHealthReport:
    """Structured diagnostics describing the infrastructure state."""

    platform: str
    supports_admin_access: bool
    registered_services: tuple[str, ...]
    missing_core_services: tuple[str, ...]
    refreshable_counts: Mapping[str, int]
    shutdown: bool
    aliases: Mapping[str, str]
    tagged_services: Mapping[str, tuple[str, ...]]
    active_scopes: tuple[str, ...]
    scope_snapshots: Mapping[str, tuple[str, ...]]
    core_service_status: Mapping[str, bool]
    installed_modules: tuple[str, ...]
    module_dependencies: Mapping[str, tuple[str, ...]]
    module_descriptions: Mapping[str, str | None]
    service_dependencies: Mapping[str, tuple[str, ...]]
    service_metrics: Mapping[str, ServiceRuntimeMetrics]
    service_resilience: Mapping[str, Mapping[str, Any] | None]
    resolution_history: tuple[ServiceResolutionEvent, ...]
    resolution_observers: int
    resolution_failures: Mapping[str, int]
    slow_services: Mapping[str, float]
    last_failure_messages: Mapping[str, str | None]
    recovery_counts: Mapping[str, int]
    service_health: tuple[ServiceHealthStatus, ...]
    service_topology: ServiceTopology
    critical_services_healthy: bool


class AppInfrastructure:
    """Coordinate service registration, module loading, and refresh tracking."""

    def __init__(
        self,
        app: Any,
        *,
        extra_modules: Iterable[ServiceModule] | None = None,
        slow_resolution_threshold: float = 0.1,
    ) -> None:
        self._app = app
        self.registry = ServiceRegistry()
        self._slow_resolution_threshold = max(0.0, slow_resolution_threshold)
        self._refreshables: dict[str, _RefreshableStore] = {
            "fonts": _RefreshableStore(),
            "theme": _RefreshableStore(),
        }
        self._view_store: ViewStore | None = None
        self._shutdown = False
        self._extra_modules = tuple(extra_modules or ())
        self._core_services = (
            "app",
            "config",
            "app_state",
            "thread_manager",
            "theme_manager",
        )
        self._ui_scope: ServiceScope | None = None
        self._default_modules = self._build_default_modules()
        self._resolution_lock = threading.RLock()
        self._resolution_failure_counts: dict[str, int] = {}
        self._resolution_last_failure_messages: dict[str, str | None] = {}
        self._resolution_slow_services: dict[str, float] = {}
        self._resolution_recovery_counts: dict[str, int] = {}
        self.registry.add_resolution_observer(self._capture_resolution_event)
        self._announce_platform_support()
        self._install_default_modules()
        if self._extra_modules:
            self.install_modules(self._extra_modules)
        self._verify_core_services()

    # ------------------------------------------------------------------
    def _build_default_modules(self) -> tuple[ServiceModule, ...]:
        def _configure_core(registry: ServiceRegistry) -> None:
            registry.register_instance(
                "app",
                self._app,
                tags={"core"},
                health_check=self._health_check_app,
                critical=True,
            )
            registry.register(
                "config",
                lambda reg: Config(),
                tags={"core"},
                contract=Config,
                health_check=self._health_check_config,
                critical=True,
            )
            registry.register(
                "app_state",
                lambda reg: AppState(),
                tags={"core"},
                contract=AppState,
                dependencies=("config",),
                health_check=self._health_check_app_state,
                critical=True,
            )
            registry.register(
                "thread_manager",
                lambda reg: ThreadManager(),
                tags={"core", "lifecycle"},
                on_close=self._safe_stop_thread_manager,
                contract=ThreadManager,
                dependencies=("config",),
                validator=self._validate_thread_manager,
                health_check=self._health_check_thread_manager,
                critical=True,
            )
            registry.register(
                "theme_manager",
                self._build_theme_manager,
                tags={"ui"},
                aliases=("theme",),
                contract=ThemeManager,
                dependencies=("config",),
                validator=self._validate_theme_manager,
                health_check=self._health_check_theme_manager,
                critical=True,
            )

        def _configure_ui(registry: ServiceRegistry) -> None:
            scope = self._ensure_ui_scope(force_new=True)

            def _close_scope(target: ServiceScope) -> None:
                if not target.is_closed():
                    target.close()

            registry.register_instance(
                "ui_scope",
                scope,
                tags={"ui", "scope"},
                on_close=_close_scope,
                replace=True,
                contract=ServiceScope,
            )

        return (
            ServiceModule(
                name="core-services",
                configure=_configure_core,
                description="Registers core CoolBox services and lifecycle wiring.",
            ),
            ServiceModule(
                name="ui-services",
                configure=_configure_ui,
                dependencies=("core-services",),
                description="Prepares UI-scoped helpers for refresh coordination.",
            ),
        )

    def _install_default_modules(self) -> None:
        for module in self._default_modules:
            if not self.registry.is_module_installed(module.name):
                self.registry.install_module(module)

    def install_modules(self, modules: Iterable[ServiceModule]) -> None:
        for module in modules:
            self.registry.install_module(module)

    def _ensure_ui_scope(self, *, force_new: bool = False) -> ServiceScope:
        if force_new and self._ui_scope is not None and not self._ui_scope.is_closed():
            self._ui_scope.close()
            self._ui_scope = None
        if self._ui_scope is None or self._ui_scope.is_closed():
            self._ui_scope = self.registry.create_scope("ui")
        return self._ui_scope

    @staticmethod
    def _safe_stop_thread_manager(manager: ThreadManager) -> None:
        threads = (
            manager.logger_thread,
            manager.process_thread,
            manager.monitor_thread,
        )
        if any(thread.is_alive() for thread in threads):
            manager.stop()
        else:
            manager.shutdown.set()

    @staticmethod
    def _validate_thread_manager(manager: ThreadManager, registry: ServiceRegistry) -> None:
        required = ["shutdown", "start", "stop"]
        missing = [name for name in required if not hasattr(manager, name)]
        if missing:
            raise AttributeError(
                f"ThreadManager is missing expected attributes: {', '.join(missing)}"
            )
        shutdown_attr = getattr(manager, "shutdown")
        if not hasattr(shutdown_attr, "is_set"):
            raise TypeError("ThreadManager.shutdown must expose an Event-like interface")

    @staticmethod
    def _validate_theme_manager(manager: ThemeManager, registry: ServiceRegistry) -> None:
        required = ["bind_config", "apply_theme", "get_theme"]
        missing = [name for name in required if not hasattr(manager, name)]
        if missing:
            raise AttributeError(
                f"ThemeManager is missing expected methods: {', '.join(missing)}"
            )
        if not registry.is_registered("config"):
            raise RuntimeError("Config service must be registered before ThemeManager")

    @staticmethod
    def _health_check_app(app: Any, registry: ServiceRegistry) -> HealthCheckResult:
        healthy = app is not None
        details = None if healthy else "Application reference is unavailable"
        return HealthCheckResult(healthy, details)

    @staticmethod
    def _health_check_config(config: Config, registry: ServiceRegistry) -> HealthCheckResult:
        healthy = hasattr(config, "config") and isinstance(config.config, dict)
        details: str | None = None
        if healthy and getattr(config, "load_ok", True) is False:
            healthy = False
            details = "Configuration failed to load cleanly"
        elif not healthy:
            details = "Configuration storage is not initialised"
        return HealthCheckResult(healthy, details)

    @staticmethod
    def _health_check_app_state(state: AppState, registry: ServiceRegistry) -> HealthCheckResult:
        healthy = isinstance(state.current_view, str)
        details = None if healthy else "current_view is not a string"
        return HealthCheckResult(healthy, details)

    @staticmethod
    def _health_check_thread_manager(
        manager: ThreadManager, registry: ServiceRegistry
    ) -> HealthCheckResult:
        shutdown_event = getattr(manager, "shutdown", None)
        healthy = bool(shutdown_event is not None and hasattr(shutdown_event, "is_set"))
        if healthy:
            healthy = not shutdown_event.is_set()  # type: ignore[union-attr]
        details = None if healthy else "ThreadManager shutdown event is set"
        return HealthCheckResult(healthy, details)

    @staticmethod
    def _health_check_theme_manager(
        manager: ThemeManager, registry: ServiceRegistry
    ) -> HealthCheckResult:
        try:
            theme = manager.get_theme()
        except Exception as exc:  # pragma: no cover - defensive
            return HealthCheckResult(False, f"Theme retrieval failed: {exc}")
        healthy = isinstance(theme, dict)
        details = None if healthy else "Theme data is not a mapping"
        return HealthCheckResult(healthy, details)

    def _build_theme_manager(self, registry: ServiceRegistry) -> ThemeManager:
        config = registry.require("config", Config)
        manager = ThemeManager(config=config)
        manager.bind_config(config)
        return manager

    # ------------------------------------------------------------------
    def require(
        self,
        name: str,
        expected_type: type[T] | tuple[type[Any], ...] | None = None,
        *,
        scope: ServiceScope | None = None,
    ) -> T:
        if scope is None:
            instance = self.registry.require(name, expected_type)
            return instance
        instance = scope.require(name, expected_type)
        return instance

    # ------------------------------------------------------------------
    def resolution_insights(self) -> ResolutionInsights:
        with self._resolution_lock:
            return ResolutionInsights(
                slow_services=dict(self._resolution_slow_services),
                failure_counts=dict(self._resolution_failure_counts),
                last_failure_messages=dict(self._resolution_last_failure_messages),
                recovery_counts=dict(self._resolution_recovery_counts),
            )

    def clear_resolution_insights(self) -> None:
        with self._resolution_lock:
            self._resolution_slow_services.clear()
            self._resolution_failure_counts.clear()
            self._resolution_last_failure_messages.clear()
            self._resolution_recovery_counts.clear()

    def _capture_resolution_event(self, event: ServiceResolutionEvent) -> None:
        with self._resolution_lock:
            if not event.success:
                if event.retry_scheduled:
                    if event.error is not None:
                        self._resolution_last_failure_messages[event.name] = event.error
                    return
                if event.recovered:
                    self._resolution_recovery_counts[event.name] = (
                        self._resolution_recovery_counts.get(event.name, 0) + 1
                    )
                else:
                    self._resolution_failure_counts[event.name] = (
                        self._resolution_failure_counts.get(event.name, 0) + 1
                    )
                    self._resolution_last_failure_messages[event.name] = event.error
            else:
                if event.recovered:
                    self._resolution_recovery_counts[event.name] = (
                        self._resolution_recovery_counts.get(event.name, 0) + 1
                    )
                    self._resolution_last_failure_messages.pop(event.name, None)
                elif event.error is None:
                    self._resolution_last_failure_messages.pop(event.name, None)
                if (
                    event.duration is not None
                    and event.duration >= self._slow_resolution_threshold
                    and not event.from_cache
                ):
                    previous = self._resolution_slow_services.get(event.name)
                    if previous is None or event.duration > previous:
                        self._resolution_slow_services[event.name] = event.duration

    def register_refreshable(
        self,
        target: Any,
        *,
        fonts: bool = False,
        theme: bool = False,
        auto_detect: bool = True,
    ) -> None:
        if target is None:
            return
        if auto_detect:
            fonts = fonts or hasattr(target, "refresh_fonts")
            theme = theme or hasattr(target, "refresh_theme")
        if fonts:
            self._refreshables["fonts"].add(target)
        if theme:
            self._refreshables["theme"].add(target)

    def unregister_refreshable(self, target: Any) -> None:
        if target is None:
            return
        for store in self._refreshables.values():
            store.remove(target)

    def iter_refreshables(self, kind: str) -> Iterator[Any]:
        try:
            store = self._refreshables[kind]
        except KeyError as exc:
            raise KeyError(f"Unknown refreshable kind: {kind}") from exc
        yield from store.iter_alive()

    # ------------------------------------------------------------------
    def broadcast_refresh(self, *, fonts: bool = False, theme: bool = False) -> None:
        if fonts:
            for widget in self.iter_refreshables("fonts"):
                refresher = getattr(widget, "refresh_fonts", None)
                if callable(refresher):
                    try:
                        refresher()
                    except Exception:  # pragma: no cover - defensive
                        logger.exception("Font refresh failed for %s", widget)
        if theme:
            for widget in self.iter_refreshables("theme"):
                refresher = getattr(widget, "refresh_theme", None)
                if callable(refresher):
                    try:
                        refresher()
                    except Exception:  # pragma: no cover - defensive
                        logger.exception("Theme refresh failed for %s", widget)

    # ------------------------------------------------------------------
    def create_view_store(self, initial: Mapping[str, Any] | None = None) -> ViewStore:
        store = ViewStore(self, initial)
        self._view_store = store
        scope = self._ensure_ui_scope()
        try:
            scope.attach_instance(
                "view-store",
                store,
                on_close=self._dispose_view_store,
                replace=True,
            )
        except RuntimeError:
            scope = self._ensure_ui_scope(force_new=True)
            scope.attach_instance(
                "view-store",
                store,
                on_close=self._dispose_view_store,
                replace=True,
            )
        return store

    @staticmethod
    def _dispose_view_store(store: ViewStore) -> None:
        try:
            store.clear()
        except Exception:  # pragma: no cover - defensive cleanup
            logger.exception("Failed to dispose view store cleanly")

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        try:
            try:
                self.registry.remove_resolution_observer(self._capture_resolution_event)
            except KeyError:
                pass
            self.registry.shutdown()
            self.clear_resolution_insights()
        finally:
            for store in self._refreshables.values():
                store.clear()
            if self._view_store is not None:
                self._view_store.clear()
                self._view_store = None
            if self._ui_scope is not None and not self._ui_scope.is_closed():
                self._ui_scope.close()
            self._ui_scope = None

    # ------------------------------------------------------------------
    def health_snapshot(self) -> tuple[ServiceHealthStatus, ...]:
        """Return the current service health snapshot."""

        return self.registry.health_snapshot()

    def critical_services_healthy(self) -> bool:
        """Return whether all critical services currently report healthy."""

        return all(
            status.healthy or not status.critical for status in self.health_snapshot()
        )

    def service_topology(self) -> ServiceTopology:
        """Return the current service dependency topology."""

        return self.registry.service_topology()

    # ------------------------------------------------------------------
    def diagnose(self) -> InfrastructureHealthReport:
        """Return a diagnostics snapshot describing infrastructure health."""

        platform_name = platform.system() or "Unknown"
        registered = tuple(self.registry.registered_services())
        core_status = {service: self.registry.is_registered(service) for service in self._core_services}
        missing = tuple(sorted(service for service, present in core_status.items() if not present))
        refreshable_counts = {
            kind: sum(1 for _ in store.iter_alive())
            for kind, store in self._refreshables.items()
        }
        aliases = dict(self.registry.alias_map())
        tagged_services = dict(self.registry.tags_index())
        scope_snapshots = dict(self.registry.scope_snapshots())
        active_scopes = self.registry.active_scopes()
        installed_modules = self.registry.installed_modules()
        module_dependencies = dict(self.registry.module_dependencies())
        module_descriptions = dict(self.registry.module_descriptions())
        service_dependencies = dict(self.registry.service_dependencies())
        service_metrics = dict(self.registry.service_metrics())
        service_resilience = dict(self.registry.service_resilience_policies())
        resolution_history = self.registry.resolution_history()
        resolution_observers = self.registry.resolution_observer_count()
        insights = self.resolution_insights()
        service_health = self.registry.health_snapshot()
        topology = self.registry.service_topology()
        critical_healthy = all(
            status.healthy or not status.critical for status in service_health
        )
        return InfrastructureHealthReport(
            platform=platform_name,
            supports_admin_access=self.supports_admin_access(),
            registered_services=registered,
            missing_core_services=missing,
            refreshable_counts=refreshable_counts,
            shutdown=self._shutdown,
            aliases=aliases,
            tagged_services=tagged_services,
            active_scopes=active_scopes,
            scope_snapshots=scope_snapshots,
            core_service_status=core_status,
            installed_modules=installed_modules,
            module_dependencies=module_dependencies,
            module_descriptions=module_descriptions,
            service_dependencies=service_dependencies,
            service_metrics=service_metrics,
            service_resilience=service_resilience,
            resolution_history=resolution_history,
            resolution_observers=resolution_observers,
            resolution_failures=dict(insights.failure_counts),
            slow_services=dict(insights.slow_services),
            last_failure_messages=dict(insights.last_failure_messages),
            recovery_counts=dict(insights.recovery_counts),
            service_health=service_health,
            service_topology=topology,
            critical_services_healthy=critical_healthy,
        )

    def supports_admin_access(self) -> bool:
        """Return whether the current platform has verified administrator support."""

        return (platform.system() or "").lower() == "darwin"

    # ------------------------------------------------------------------
    def service_scope(self, name: str | None = None) -> ContextManager[ServiceScope]:
        """Context manager yielding a new service scope."""

        @contextmanager
        def _manager() -> Iterator[ServiceScope]:
            scope = self.registry.create_scope(name)
            try:
                yield scope
            finally:
                scope.close()

        return _manager()

    # ------------------------------------------------------------------
    def _announce_platform_support(self) -> None:
        system_name = platform.system() or "Unknown"
        if system_name == "Darwin":
            logger.info(
                "Administrator access also works on macOS without an issue and needs no additional configuration."
            )
        else:
            logger.debug("AppInfrastructure initialized for platform: %s", system_name)

    def _verify_core_services(self) -> None:
        missing = [service for service in self._core_services if not self.registry.is_registered(service)]
        if missing:
            raise RuntimeError(f"Missing core services: {', '.join(missing)}")
