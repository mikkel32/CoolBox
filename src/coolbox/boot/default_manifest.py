"""Bundled boot manifest data used when PyYAML is unavailable."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

_DEFAULT_MANIFEST: dict[str, Any] = {
    "profiles": {
        "default": {
            "orchestrator": {
                "stages": [
                    "preflight",
                    "dependency-resolution",
                    "installers",
                    "verification",
                    "summaries",
                ],
                "load_plugins": True,
            },
            "preload": {
                "modules": [
                    "coolbox.console.dashboard",
                    "coolbox.utils.logging_config",
                ],
                "callables": [],
            },
            "recovery": {
                "dashboard": {
                    "mode": "json",
                    "theme": "minimal",
                    "layout": "minimal",
                },
                "hints": [
                    "Review setup diagnostics before relaunching.",
                    "Run coolbox --profile recovery to execute extended checks.",
                ],
                "stages": [
                    "verification",
                    "summaries",
                ],
            },
        },
        "recovery": {
            "orchestrator": {
                "stages": [
                    "verification",
                    "summaries",
                ],
                "load_plugins": False,
            },
            "preload": {
                "modules": [
                    "coolbox.console.dashboard",
                ],
                "callables": [],
            },
            "recovery": {
                "dashboard": {
                    "mode": "json",
                    "theme": "high-contrast",
                    "layout": "horizontal",
                },
                "hints": [
                    "Inspect verification output for actionable errors.",
                ],
            },
        },
    }
}


def get_default_manifest() -> Mapping[str, Any]:
    """Return a copy of the bundled boot manifest."""

    return deepcopy(_DEFAULT_MANIFEST)


__all__ = ["get_default_manifest"]
