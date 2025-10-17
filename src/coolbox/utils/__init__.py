"""Domain-organized entry points for CoolBox utility helpers."""
from __future__ import annotations

import os
import sys
from importlib import import_module
from typing import Any, Iterable

_EXPORT_MAP: dict[str, tuple[str, str]] = {}
_STATIC_EXPORTS: dict[str, Any] = {}
_MODULE_EXPORTS: list[str] = []


def _add_exports(module: str, names: Iterable[str]) -> None:
    """Register ``names`` from ``module`` for lazy re-export."""

    _EXPORT_MAP.update({name: (module, name) for name in names})


# -- Filesystem helpers -------------------------------------------------------
_add_exports(
    "coolbox.utils.files.file_manager",
    [
        "FileManagerError",
        "read_text",
        "write_text",
        "read_lines",
        "write_lines",
        "read_bytes",
        "write_bytes",
        "read_json",
        "write_json",
        "atomic_write",
        "atomic_write_bytes",
        "ensure_dir",
        "touch_file",
        "pick_file",
        "copy_file",
        "move_file",
        "delete_file",
        "list_files",
        "copy_dir",
        "move_dir",
        "delete_dir",
    ],
)
_add_exports(
    "coolbox.utils.files.cache",
    [
        "CacheItem",
        "CacheManager",
    ],
)

# -- System helpers -----------------------------------------------------------
_add_exports(
    "coolbox.utils.system",
    [
        "open_path",
        "slugify",
        "strip_ansi",
        "get_system_info",
        "get_system_metrics",
        "run_with_spinner",
        "console",
    ],
)
_add_exports(
    "coolbox.utils.system.hash_utils",
    [
        "calc_data_hash",
        "calc_hash",
        "calc_hash_cached",
        "calc_hashes",
    ],
)
_add_exports("coolbox.utils.system.vm", ["launch_vm_debug"])
_add_exports("coolbox.utils.system.gpu", ["benchmark_gpu_usage"])

# -- Display helpers ----------------------------------------------------------
_add_exports(
    "coolbox.utils.display.color_utils",
    [
        "lighten_color",
        "darken_color",
        "adjust_color",
        "hex_brightness",
    ],
)
_add_exports(
    "coolbox.utils.display.rainbow",
    ["RainbowBorder", "NeonPulseBorder"],
)
_add_exports("coolbox.utils.display.hover_tracker", ["HoverTracker"])
_add_exports(
    "coolbox.utils.display.mouse_listener",
    ["capture_mouse", "get_global_listener", "is_supported", "log"],
)
_add_exports(
    "coolbox.utils.display.theme",
    ["ThemeManager", "_ConfigLike"],
)

if not os.environ.get("COOLBOX_LIGHTWEIGHT"):
    _add_exports(
        "coolbox.utils.display.ui",
        ["center_window", "get_screen_refresh_rate"],
    )
else:  # pragma: no cover - lightweight test mode

    def _fallback_center_window(*_args: object, **_kwargs: object) -> None:
        """Fallback no-op when UI helpers are intentionally disabled."""

    def _fallback_refresh_rate(*_args: object, **_kwargs: object) -> int:
        """Return a conservative refresh rate without probing the system."""

        return 60

    _STATIC_EXPORTS.update(
        {
            "center_window": _fallback_center_window,
            "get_screen_refresh_rate": _fallback_refresh_rate,
        }
    )

# -- Network helpers ----------------------------------------------------------
_add_exports(
    "coolbox.utils.network",
    [
        "scan_ports",
        "async_scan_ports",
        "scan_port_list",
        "async_scan_port_list",
        "scan_top_ports",
        "async_scan_top_ports",
        "scan_targets",
        "scan_targets_list",
        "async_scan_targets",
        "async_scan_targets_list",
        "async_auto_scan_iter",
        "async_auto_scan",
        "async_scan_hosts_iter",
        "async_scan_hosts_detailed",
        "async_get_http_info",
        "async_collect_http_info",
        "AutoScanInfo",
        "HTTPInfo",
        "get_mac_address",
        "async_get_mac_address",
        "get_mac_vendor",
        "_guess_os_from_ttl",
        "_guess_device_type",
        "_estimate_risk",
        "async_filter_active_hosts",
        "async_detect_local_hosts",
        "detect_local_hosts",
        "detect_arp_hosts",
        "async_get_hostname",
        "auto_scan_info_to_dict",
        "auto_scan_results_to_dict",
        "clear_dns_cache",
        "clear_local_host_cache",
        "parse_port_range",
        "parse_ports",
        "ports_as_range",
        "parse_hosts",
        "clear_scan_cache",
        "clear_host_cache",
        "clear_http_cache",
        "clear_ping_cache",
        "clear_arp_cache",
        "TOP_PORTS",
        "PortInfo",
    ],
)

# -- Process helpers ----------------------------------------------------------
_add_exports("coolbox.utils.processes.monitor", ["ProcessEntry", "ProcessWatcher"])
_add_exports("coolbox.utils.processes.cache", ["ProcessCache"])
_add_exports("coolbox.utils.processes.kill", ["kill_process", "kill_process_tree"])
_add_exports(
    "coolbox.utils.processes.utils",
    [
        "run_command_async_ex",
        "run_command_ex",
        "run_command_async",
        "run_command",
        "run_command_background",
    ],
)
_add_exports("coolbox.utils.processes.thread_manager", ["ThreadManager"])

# -- Security helpers ---------------------------------------------------------
if not os.environ.get("COOLBOX_LIGHTWEIGHT"):
    _add_exports(
        "coolbox.utils.security",
        [
            "is_firewall_enabled",
            "set_firewall_enabled",
            "is_defender_realtime_on",
            "set_defender_enabled",
            "set_defender_realtime",
            "is_admin",
            "ensure_admin",
            "get_defender_status",
            "relaunch_security_center",
        ],
    )

# -- Analysis helpers ---------------------------------------------------------
_add_exports(
    "coolbox.utils.analysis.scoring_engine",
    ["ScoringEngine", "Tuning", "tuning"],
)


for module_name in [
    "file_manager",
]:
    try:
        module = import_module(f"{__name__}.{module_name}")
    except Exception:  # pragma: no cover - optional dependencies missing
        if module_name in {"ui", "hover_tracker", "mouse_listener", "theme"} and os.environ.get(
            "COOLBOX_LIGHTWEIGHT"
        ):
            continue
        raise
    setattr(sys.modules[__name__], module_name, module)
    _MODULE_EXPORTS.append(module_name)


def __getattr__(name: str) -> Any:
    if name in _STATIC_EXPORTS:
        return _STATIC_EXPORTS[name]
    try:
        module_name, attr = _EXPORT_MAP[name]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise AttributeError(name) from exc
    module = import_module(module_name)
    value = getattr(module, attr)
    setattr(sys.modules[__name__], name, value)
    return value


def __dir__() -> list[str]:
    names = set(_EXPORT_MAP)
    names.update(_STATIC_EXPORTS)
    names.update(_MODULE_EXPORTS)
    return sorted(names)


__all__ = __dir__()
