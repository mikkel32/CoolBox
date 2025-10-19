"""Typed boot manifest schema for plugin runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


class ManifestError(RuntimeError):
    """Raised when a manifest cannot be parsed into the typed schema."""


class ManifestValidationError(ManifestError):
    """Raised when a manifest fails schema validation."""


def _coerce_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (str(value),)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return (str(value),)


def _coerce_mapping(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): str(val) for key, val in value.items()}
    raise ManifestError(f"Expected mapping value, received: {type(value)!r}")


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"", "0", "false", "no", "off"}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
    raise ManifestError(f"Invalid boolean flag: {value!r}")


@dataclass(slots=True)
class PluginCapabilities:
    """Declared capability surface for a plugin worker."""

    provides: tuple[str, ...]
    requires: tuple[str, ...]
    sandbox: tuple[str, ...]


@dataclass(slots=True)
class PluginIOSchema:
    """Input/output schema advertised by a plugin."""

    inputs: Mapping[str, str]
    outputs: Mapping[str, str]


@dataclass(slots=True)
class ResourceBudget:
    """Resource budget constraints for a plugin runtime."""

    cpu: str | None
    memory: str | None
    disk: str | None
    gpu: str | None
    timeout: int | None


@dataclass(slots=True)
class StartupHooks:
    """Hook callables executed during lifecycle transitions."""

    before: tuple[str, ...]
    after: tuple[str, ...]
    on_failure: tuple[str, ...]


@dataclass(slots=True)
class RuntimeConfiguration:
    """Union of runtime configuration for supported backends."""

    kind: str
    entrypoint: str | None = None
    module: str | None = None
    handler: str | None = None
    wasi: bool = False
    features: tuple[str, ...] = field(default_factory=tuple)
    environment: Mapping[str, str] = field(default_factory=dict)
    interpreter: "RuntimeInterpreter | None" = None
    build: "RuntimeBuild | None" = None
    lockfile: Path | None = None
    runtimes: tuple[str, ...] = field(default_factory=tuple)
    wasm: "WasmPackaging | None" = None

    @property
    def is_native(self) -> bool:
        return self.kind == "native"

    @property
    def is_wasm(self) -> bool:
        return self.kind == "wasm"


@dataclass(slots=True)
class PluginDevSettings:
    """Development flags attached to a plugin definition."""

    hot_reload: bool
    watch_paths: tuple[Path, ...]
    locales: tuple[str, ...]


@dataclass(slots=True)
class PluginDefinition:
    """Full plugin definition loaded from the manifest."""

    identifier: str
    runtime: RuntimeConfiguration
    capabilities: PluginCapabilities
    io: PluginIOSchema
    resources: ResourceBudget
    hooks: StartupHooks
    dev: PluginDevSettings
    version: str | None = None
    description: str | None = None
    toolbus: "ToolBusDeclaration | None" = None


@dataclass(slots=True)
class ToolBusDeclaration:
    """Tool bus endpoints declared by a plugin."""

    invoke: Mapping[str, str]
    stream: Mapping[str, str]
    subscribe: Mapping[str, str]


@dataclass(slots=True)
class ProfileDevSettings:
    """Profile level development options."""

    hot_reload: bool
    watch_paths: tuple[Path, ...]
    locales: tuple[str, ...]


@dataclass(slots=True)
class BootProfile:
    """Full configuration for a boot profile."""

    orchestrator: Mapping[str, Any]
    preload: Mapping[str, Any]
    recovery: Mapping[str, Any]
    plugins: tuple[PluginDefinition, ...]
    dev: ProfileDevSettings
    recovery_profile: str | None = None


@dataclass(slots=True)
class BootManifest:
    """Manifest document describing profiles."""

    profiles: Mapping[str, BootProfile]


@dataclass(slots=True)
class RuntimeInterpreter:
    """Interpreter constraints for plugin execution environments."""

    python: tuple[str, ...]
    implementation: str | None
    platforms: tuple[str, ...]
    extras: Mapping[str, str]


@dataclass(slots=True)
class RuntimeBuildStep:
    """Declarative step that may be executed during plugin packaging."""

    name: str
    command: tuple[str, ...]
    shell: bool
    cwd: Path | None
    environment: Mapping[str, str]


@dataclass(slots=True)
class RuntimeBuild:
    """Build plan declared by the plugin runtime."""

    steps: tuple[RuntimeBuildStep, ...]
    lockfile: Path | None


@dataclass(slots=True)
class WasmPackaging:
    """Metadata describing WASM artefacts for polyglot plugins."""

    module: Path
    runtimes: tuple[str, ...]
    entrypoint: str | None
    build: RuntimeBuild | None


def _parse_runtime(entry: Mapping[str, Any]) -> RuntimeConfiguration:
    kind = str(entry.get("kind", "native")).lower()
    entrypoint = entry.get("entrypoint")
    module = entry.get("module")
    handler = entry.get("handler")
    wasi = _coerce_bool(entry.get("wasi"), default=False)
    features = _coerce_sequence(entry.get("features"))
    environment = _coerce_mapping(entry.get("environment")) if entry.get("environment") else {}
    interpreter = _parse_runtime_interpreter(entry.get("interpreter"))
    build = _parse_runtime_build(entry.get("build"))
    lock_raw = entry.get("lockfile")
    lockfile = Path(str(lock_raw)) if lock_raw else None
    runtimes = _coerce_sequence(entry.get("runtimes"))
    wasm = _parse_wasm_packaging(entry.get("wasm"))
    return RuntimeConfiguration(
        kind=kind,
        entrypoint=str(entrypoint) if entrypoint else None,
        module=str(module) if module else None,
        handler=str(handler) if handler else None,
        wasi=wasi,
        features=features,
        environment=environment,
        interpreter=interpreter,
        build=build,
        lockfile=lockfile,
        runtimes=runtimes,
        wasm=wasm,
    )


def _parse_capabilities(entry: Mapping[str, Any]) -> PluginCapabilities:
    provides = _coerce_sequence(entry.get("provides"))
    requires = _coerce_sequence(entry.get("requires"))
    sandbox = _coerce_sequence(entry.get("sandbox"))
    return PluginCapabilities(provides=provides, requires=requires, sandbox=sandbox)


def _parse_io(entry: Mapping[str, Any]) -> PluginIOSchema:
    inputs = _coerce_mapping(entry.get("inputs")) if isinstance(entry, Mapping) else {}
    outputs = _coerce_mapping(entry.get("outputs")) if isinstance(entry, Mapping) else {}
    return PluginIOSchema(inputs=inputs, outputs=outputs)


def _parse_resources(entry: Mapping[str, Any]) -> ResourceBudget:
    cpu = entry.get("cpu")
    memory = entry.get("memory")
    disk = entry.get("disk")
    gpu = entry.get("gpu")
    timeout = entry.get("timeout")
    timeout_value = int(timeout) if timeout is not None else None
    return ResourceBudget(
        cpu=str(cpu) if cpu is not None else None,
        memory=str(memory) if memory is not None else None,
        disk=str(disk) if disk is not None else None,
        gpu=str(gpu) if gpu is not None else None,
        timeout=timeout_value,
    )


def _parse_hooks(entry: Mapping[str, Any]) -> StartupHooks:
    before = _coerce_sequence(entry.get("before"))
    after = _coerce_sequence(entry.get("after"))
    on_failure = _coerce_sequence(entry.get("on_failure"))
    return StartupHooks(before=before, after=after, on_failure=on_failure)


def _parse_dev(entry: Mapping[str, Any] | None, *, default_hot_reload: bool = False) -> PluginDevSettings:
    if entry is None:
        entry = {}
    hot_reload = _coerce_bool(entry.get("hot_reload"), default=default_hot_reload)
    watch_raw = entry.get("watch")
    if isinstance(watch_raw, Mapping):
        watch_iter = watch_raw.values()
    else:
        watch_iter = watch_raw
    watch_paths = tuple(Path(str(path)) for path in _coerce_sequence(watch_iter))
    locales = _coerce_sequence(entry.get("locales"))
    return PluginDevSettings(hot_reload=hot_reload, watch_paths=watch_paths, locales=locales)


def _parse_profile_dev(entry: Mapping[str, Any] | None) -> ProfileDevSettings:
    hot_reload = _coerce_bool((entry or {}).get("hot_reload"), default=False)
    watch_iter: Sequence[str] | Mapping[str, Any] | None = (entry or {}).get("watch")
    if isinstance(watch_iter, Mapping):
        watch_values = watch_iter.values()
    else:
        watch_values = watch_iter
    watch_paths = tuple(Path(str(path)) for path in _coerce_sequence(watch_values))
    locales = _coerce_sequence((entry or {}).get("locales"))
    return ProfileDevSettings(hot_reload=hot_reload, watch_paths=watch_paths, locales=locales)


def _parse_toolbus(entry: Mapping[str, Any] | None) -> ToolBusDeclaration | None:
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise ManifestError("Plugin 'toolbus' section must be a mapping")

    def _mapping(key: str) -> Mapping[str, str]:
        value = entry.get(key, {})
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ManifestError(f"toolbus.{key} must be a mapping")
        return {str(name): str(target) for name, target in value.items()}

    return ToolBusDeclaration(
        invoke=_mapping("invoke"),
        stream=_mapping("stream"),
        subscribe=_mapping("subscribe"),
    )


def _parse_plugin(entry: Mapping[str, Any], default_hot_reload: bool) -> PluginDefinition:
    identifier = str(entry.get("id"))
    description = entry.get("description")
    version = entry.get("version")
    runtime = _parse_runtime(entry.get("runtime", {}))
    capabilities = _parse_capabilities(entry.get("capabilities", {}))
    io = _parse_io(entry.get("io", {}))
    resources = _parse_resources(entry.get("resources", {}))
    hooks = _parse_hooks(entry.get("hooks", {}))
    dev = _parse_dev(entry.get("dev", {}), default_hot_reload=default_hot_reload)
    toolbus = _parse_toolbus(entry.get("toolbus"))
    return PluginDefinition(
        identifier=identifier,
        version=str(version) if version else None,
        runtime=runtime,
        capabilities=capabilities,
        io=io,
        resources=resources,
        hooks=hooks,
        dev=dev,
        description=str(description) if description else None,
        toolbus=toolbus,
    )


def _parse_runtime_interpreter(entry: Mapping[str, Any] | None) -> RuntimeInterpreter | None:
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise ManifestError("Runtime interpreter block must be a mapping")
    python_versions = _coerce_sequence(entry.get("python"))
    implementation = entry.get("implementation")
    platforms = _coerce_sequence(entry.get("platforms"))
    extras = _coerce_mapping(entry.get("extras")) if entry.get("extras") else {}
    return RuntimeInterpreter(
        python=python_versions,
        implementation=str(implementation) if implementation else None,
        platforms=platforms,
        extras=extras,
    )


def _parse_runtime_build(entry: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None) -> RuntimeBuild | None:
    if entry is None:
        return None
    if isinstance(entry, Mapping) and "steps" not in entry and "lockfile" not in entry:
        # shorthand form: treat mapping as single step definition
        steps_entry = [entry]
        lockfile_raw = None
    elif isinstance(entry, Mapping):
        steps_entry = entry.get("steps", [])
        lockfile_raw = entry.get("lockfile")
    else:
        steps_entry = entry
        lockfile_raw = None
    if steps_entry is None:
        steps_entry = []
    if not isinstance(steps_entry, Iterable):
        raise ManifestError("Runtime build steps must be a sequence")
    steps: list[RuntimeBuildStep] = []
    for step in steps_entry:
        if not isinstance(step, Mapping):
            raise ManifestError("Runtime build step entries must be mappings")
        name = str(step.get("name") or step.get("id") or f"step{len(steps)+1}")
        command_entry = step.get("command")
        if isinstance(command_entry, (str, bytes)):
            command = tuple(str(part) for part in command_entry.split())
        elif isinstance(command_entry, Iterable):
            command = tuple(str(part) for part in command_entry)
        elif command_entry is None:
            command = ()
        else:
            raise ManifestError(f"Invalid build command for step '{name}'")
        shell = bool(step.get("shell", False))
        cwd_raw = step.get("cwd")
        cwd = Path(str(cwd_raw)) if cwd_raw else None
        environment = _coerce_mapping(step.get("environment")) if step.get("environment") else {}
        steps.append(
            RuntimeBuildStep(
                name=name,
                command=command,
                shell=shell,
                cwd=cwd,
                environment=environment,
            )
        )
    lockfile = Path(str(lockfile_raw)) if lockfile_raw else None
    return RuntimeBuild(steps=tuple(steps), lockfile=lockfile)


def _parse_wasm_packaging(entry: Mapping[str, Any] | None) -> WasmPackaging | None:
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise ManifestError("Runtime wasm section must be a mapping")
    module = entry.get("module")
    if not module:
        raise ManifestError("Runtime wasm configuration requires a 'module' field")
    runtimes = _coerce_sequence(entry.get("runtimes"))
    entrypoint = entry.get("entrypoint")
    build = _parse_runtime_build(entry.get("build")) if entry.get("build") else None
    return WasmPackaging(
        module=Path(str(module)),
        runtimes=runtimes,
        entrypoint=str(entrypoint) if entrypoint else None,
        build=build,
    )


def load_manifest_document(data: Mapping[str, Any]) -> BootManifest:
    """Parse raw manifest mapping into typed dataclasses."""

    profiles_entry = data.get("profiles")
    if not isinstance(profiles_entry, Mapping):
        raise ManifestError("'profiles' entry must be a mapping")
    profiles: MutableMapping[str, BootProfile] = {}
    for name, profile_data in profiles_entry.items():
        if not isinstance(profile_data, Mapping):
            raise ManifestError(f"Profile '{name}' must be a mapping")
        orchestrator = profile_data.get("orchestrator", {})
        if not isinstance(orchestrator, Mapping):
            raise ManifestError(f"Profile '{name}' orchestrator must be a mapping")
        preload = profile_data.get("preload", {})
        if not isinstance(preload, Mapping):
            raise ManifestError(f"Profile '{name}' preload must be a mapping")
        recovery = profile_data.get("recovery", {})
        if not isinstance(recovery, Mapping):
            raise ManifestError(f"Profile '{name}' recovery must be a mapping")
        dev_settings = _parse_profile_dev(profile_data.get("dev"))
        plugins_entry = profile_data.get("plugins", [])
        if plugins_entry is None:
            plugins_entry = []
        if not isinstance(plugins_entry, Iterable):
            raise ManifestError(f"Profile '{name}' plugins must be a sequence")
        plugin_definitions = []
        for plugin_entry in plugins_entry:
            if not isinstance(plugin_entry, Mapping):
                raise ManifestError(f"Plugin declaration in profile '{name}' must be a mapping")
            plugin_definitions.append(_parse_plugin(plugin_entry, dev_settings.hot_reload))
        recovery_profile = profile_data.get("recovery_profile")
        recovery_name = str(recovery_profile) if recovery_profile else None
        profiles[str(name)] = BootProfile(
            orchestrator=orchestrator,
            preload=preload,
            recovery=recovery,
            plugins=tuple(plugin_definitions),
            dev=dev_settings,
            recovery_profile=recovery_name,
        )
    return BootManifest(profiles=dict(profiles))


MANIFEST_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["profiles"],
    "properties": {
        "profiles": {
            "type": "object",
            "additionalProperties": {"$ref": "#/$defs/profile"},
        }
    },
    "$defs": {
        "profile": {
            "type": "object",
            "properties": {
                "orchestrator": {"type": "object"},
                "preload": {"type": "object"},
                "recovery": {"type": "object"},
                "plugins": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/plugin"},
                    "default": [],
                },
                "dev": {"$ref": "#/$defs/dev"},
                "recovery_profile": {"type": "string"},
            },
            "required": ["orchestrator", "preload", "recovery", "plugins"],
            "additionalProperties": True,
        },
        "dev": {
            "type": "object",
            "properties": {
                "hot_reload": {"type": ["boolean", "string"]},
                "watch": {
                    "type": ["array", "object"],
                    "items": {"type": ["string", "object"]},
                },
                "locales": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "additionalProperties": True,
        },
        "plugin": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "version": {"type": "string"},
                "description": {"type": "string"},
                "runtime": {"$ref": "#/$defs/runtime"},
                "capabilities": {"$ref": "#/$defs/capabilities"},
                "io": {"$ref": "#/$defs/io"},
                "resources": {"$ref": "#/$defs/resources"},
                "hooks": {"$ref": "#/$defs/hooks"},
                "dev": {"$ref": "#/$defs/dev"},
                "toolbus": {"$ref": "#/$defs/toolbus"},
            },
            "required": ["id", "runtime", "capabilities", "io", "resources", "hooks"],
            "additionalProperties": True,
        },
        "runtime": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "entrypoint": {"type": "string"},
                "module": {"type": "string"},
                "handler": {"type": "string"},
                "wasi": {"type": ["boolean", "string"]},
                "features": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "environment": {"type": "object"},
                "interpreter": {"$ref": "#/$defs/interpreter"},
                "build": {"$ref": "#/$defs/build"},
                "lockfile": {"type": "string"},
                "runtimes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "wasm": {"$ref": "#/$defs/wasm"},
            },
            "required": ["kind"],
            "additionalProperties": True,
        },
        "capabilities": {
            "type": "object",
            "properties": {
                "provides": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "requires": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "sandbox": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["provides", "requires", "sandbox"],
        },
        "io": {
            "type": "object",
            "properties": {
                "inputs": {"type": "object"},
                "outputs": {"type": "object"},
            },
            "required": ["inputs", "outputs"],
        },
        "resources": {
            "type": "object",
            "properties": {
                "cpu": {"type": ["string", "number"]},
                "memory": {"type": ["string", "number"]},
                "disk": {"type": ["string", "number"]},
                "gpu": {"type": ["string", "number"]},
                "timeout": {"type": ["integer", "string"]},
            },
            "required": ["cpu", "memory", "disk", "gpu", "timeout"],
        },
        "hooks": {
            "type": "object",
            "properties": {
                "before": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "after": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "on_failure": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["before", "after", "on_failure"],
        },
        "toolbus": {
            "type": "object",
            "properties": {
                "invoke": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "stream": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "subscribe": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
            "additionalProperties": False,
        },
        "interpreter": {
            "type": "object",
            "properties": {
                "python": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "implementation": {"type": "string"},
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "extras": {"type": "object"},
            },
            "required": ["python"],
            "additionalProperties": True,
        },
        "build": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/build_step"},
                },
                "lockfile": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "build_step": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {
                    "type": ["array", "string"],
                    "items": {"type": "string"},
                },
                "shell": {"type": ["boolean", "string"]},
                "cwd": {"type": "string"},
                "environment": {"type": "object"},
            },
            "required": ["name"],
            "additionalProperties": True,
        },
        "wasm": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "runtimes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "entrypoint": {"type": "string"},
                "build": {"$ref": "#/$defs/build"},
            },
            "required": ["module"],
            "additionalProperties": True,
        },
    },
}


__all__ = [
    "BootManifest",
    "BootProfile",
    "ManifestError",
    "ManifestValidationError",
    "PluginCapabilities",
    "PluginDefinition",
    "PluginDevSettings",
    "PluginIOSchema",
    "ProfileDevSettings",
    "ResourceBudget",
    "RuntimeConfiguration",
    "RuntimeBuild",
    "RuntimeBuildStep",
    "RuntimeInterpreter",
    "StartupHooks",
    "ToolBusDeclaration",
    "WasmPackaging",
    "load_manifest_document",
    "MANIFEST_JSON_SCHEMA",
]
