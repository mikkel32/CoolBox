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
]
