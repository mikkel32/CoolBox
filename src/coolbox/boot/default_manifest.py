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
            "plugins": [
                {
                    "id": "adaptive-remediation",
                    "description": "Telemetry-guided remediation assistant for installer flows.",
                    "runtime": {
                        "kind": "native",
                        "entrypoint": "coolbox.setup.plugins.adaptive_remediation:AdaptiveRemediationPlugin",
                        "environment": {},
                        "features": [],
                    },
                    "capabilities": {
                        "provides": ["setup.remediation"],
                        "requires": [],
                        "sandbox": ["native"],
                    },
                    "io": {
                        "inputs": {"telemetry": "coolbox.telemetry.events"},
                        "outputs": {"remediation": "coolbox.setup.results"},
                    },
                    "resources": {
                        "cpu": "250m",
                        "memory": "128Mi",
                        "disk": "64Mi",
                        "gpu": "0",
                        "timeout": 30,
                    },
                    "hooks": {
                        "before": [],
                        "after": [],
                        "on_failure": [],
                    },
                    "dev": {
                        "hot_reload": False,
                        "watch": ["src/coolbox/setup/plugins"],
                        "locales": ["en-US"],
                    },
                }
            ],
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
            "dev": {
                "hot_reload": False,
                "watch": ["src/coolbox/setup/plugins"],
                "locales": ["en-US", "es-ES"],
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
            "plugins": [],
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
            "dev": {
                "hot_reload": False,
                "watch": ["src/coolbox/setup/plugins"],
                "locales": ["en-US"],
            },
        },
    }
}


def get_default_manifest() -> Mapping[str, Any]:
    """Return a copy of the bundled boot manifest."""

    return deepcopy(_DEFAULT_MANIFEST)


__all__ = ["get_default_manifest"]
