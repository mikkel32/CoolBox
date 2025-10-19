"""Plugin manifest utilities and runtime helpers for CoolBox."""

from __future__ import annotations

from .manifest import (
    BootManifest,
    BootProfile,
    ManifestError,
    ManifestValidationError,
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ProfileDevSettings,
    ResourceBudget,
    RuntimeBuild,
    RuntimeBuildStep,
    RuntimeConfiguration,
    RuntimeInterpreter,
    StartupHooks,
    WasmPackaging,
    load_manifest_document,
    MANIFEST_JSON_SCHEMA,
    MINIMAL_MANIFEST_JSON_SCHEMA,
)
from .state import (
    PluginInitState,
    clear_plugin_init_state,
    load_plugin_init_state,
    record_plugin_init_failure,
    record_plugin_init_success,
)

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
    "RuntimeBuild",
    "RuntimeBuildStep",
    "RuntimeConfiguration",
    "RuntimeInterpreter",
    "StartupHooks",
    "WasmPackaging",
    "load_manifest_document",
    "MANIFEST_JSON_SCHEMA",
    "MINIMAL_MANIFEST_JSON_SCHEMA",
    "PluginInitState",
    "clear_plugin_init_state",
    "load_plugin_init_state",
    "record_plugin_init_failure",
    "record_plugin_init_success",
]
