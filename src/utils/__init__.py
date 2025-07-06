"""Lazy-loading utility package."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Dict

# Map exported attribute -> submodule containing the attribute
_ATTR_MODULES = {
    # helpers
    "log": "helpers",
    "open_path": "helpers",
    "slugify": "helpers",
    "calc_hash": "helpers",
    "calc_hash_cached": "helpers",
    "calc_hashes": "helpers",
    "get_system_info": "helpers",
    "get_system_metrics": "helpers",
    "lighten_color": "helpers",
    "darken_color": "helpers",
    "adjust_color": "helpers",
    "hex_brightness": "helpers",
    "run_with_spinner": "helpers",
    "console": "helpers",
    # asset helpers
    "asset_path": "assets",
    "assets_base": "assets",
    "logo_paths": "icons",
    "set_window_icon": "icons",
    # rainbow
    "RainbowBorder": "rainbow",
    "NeonPulseBorder": "rainbow",
    "MatrixBorder": "rainbow",
    # vm
    "launch_vm_debug": "vm",
    "async_launch_vm_debug": "vm",
    "available_backends": "vm",
    # file manager
    "read_text": "file_manager",
    "write_text": "file_manager",
    "pick_file": "file_manager",
    "copy_file": "file_manager",
    "move_file": "file_manager",
    "delete_file": "file_manager",
    "list_files": "file_manager",
    "copy_dir": "file_manager",
    "move_dir": "file_manager",
    "delete_dir": "file_manager",
    "file_manager": "file_manager",
    # process monitor
    "ProcessEntry": "process_monitor",
    "ProcessWatcher": "process_monitor",
    # watchdogs and blockers
    "PortWatchdog": "port_watchdog",
    "ConnectionWatchdog": "connection_watchdog",
    "NetworkMonitor": "network_monitor",
    "AsyncNetworkMonitor": "network_monitor",
    "NetworkState": "network_monitor",
    "NetworkGuard": "network_guard",
    "AsyncNetworkGuard": "network_guard",
    "ProcessBlocker": "process_blocker",
    "NetworkBaseline": "network_baseline",
    # network utilities
    "PortInfo": "network",
    "HTTPInfo": "network",
    "AutoScanInfo": "network",
    "get_mac_address": "network",
    "async_get_mac_address": "network",
    "get_mac_vendor": "network",
    "_guess_os_from_ttl": "network",
    "_guess_device_type": "network",
    "_estimate_risk": "network",
    "TOP_PORTS": "network",
    "scan_ports": "network",
    "async_scan_ports": "network",
    "scan_port_list": "network",
    "async_scan_port_list": "network",
    "scan_top_ports": "network",
    "async_scan_top_ports": "network",
    "scan_targets_list": "network",
    "async_scan_targets_list": "network",
    "scan_targets": "network",
    "async_scan_targets": "network",
    "async_auto_scan_iter": "network",
    "async_auto_scan": "network",
    "async_scan_hosts_iter": "network",
    "async_scan_hosts_detailed": "network",
    "async_get_http_info": "network",
    "async_collect_http_info": "network",
    "async_filter_active_hosts": "network",
    "async_detect_local_hosts": "network",
    "detect_local_hosts": "network",
    "detect_arp_hosts": "network",
    "async_get_hostname": "network",
    "auto_scan_info_to_dict": "network",
    "auto_scan_results_to_dict": "network",
    "clear_dns_cache": "network",
    "clear_local_host_cache": "network",
    "parse_port_range": "network",
    "parse_ports": "network",
    "ports_as_range": "network",
    "parse_hosts": "network",
    "clear_scan_cache": "network",
    "clear_host_cache": "network",
    "clear_http_cache": "network",
    "clear_ping_cache": "network",
    "clear_arp_cache": "network",
    # UI helpers
    "center_window": "ui",
    # kill utils
    "kill_process": "kill_utils",
    "kill_process_tree": "kill_utils",
    # win_console
    "hide_console": "win_console",
    "hidden_creation_flags": "win_console",
    "hide_terminal": "win_console",
    "silence_stdio": "win_console",
    # process utils
    "run_command": "process_utils",
    "run_command_async": "process_utils",
    "run_command_ex": "process_utils",
    "run_command_async_ex": "process_utils",
    "run_command_background": "process_utils",
    # scoring engine
    "ScoringEngine": "scoring_engine",
    "Tuning": "scoring_engine",
    "tuning": "scoring_engine",
    # security utilities
    "is_firewall_enabled": "security",
    "set_firewall_enabled": "security",
    "is_defender_enabled": "security",
    "set_defender_enabled": "security",
    "is_admin": "security",
    "ensure_admin": "security",
    "require_admin": "security",
    "LocalPort": "security",
    "ActiveConnection": "security",
    "refresh_process_cache": "security",
    "async_refresh_process_cache": "security",
    "resolve_host": "security",
    "clear_resolve_cache": "security",
    "async_resolve_host": "security",
    "network_snapshot": "security",
    "async_network_snapshot": "security",
    "monitor_network": "security",
    "async_monitor_network": "security",
    "list_open_ports": "security",
    "async_list_open_ports": "security",
    "list_active_connections": "security",
    "async_list_active_connections": "security",
    "kill_process_by_port": "security",
    "kill_port_range": "security",
    "kill_connections_by_remote": "security",
    "kill_connections_by_remotes": "security",
    "async_kill_connections_by_remote": "security",
    "async_kill_connections_by_remotes": "security",
    "async_kill_process_by_port": "security",
    "async_kill_port_range": "security",
    "block_port_firewall": "security",
    "async_block_port_firewall": "security",
    "unblock_port_firewall": "security",
    "async_unblock_port_firewall": "security",
    "block_remote_firewall": "security",
    "async_block_remote_firewall": "security",
    "unblock_remote_firewall": "security",
    "async_unblock_remote_firewall": "security",
    # security log
    "SecurityEvent": "security_log",
    "load_security_events": "security_log",
    "add_security_event": "security_log",
    "clear_security_events": "security_log",
    "event_counts": "security_log",
    "async_load_events": "security_log",
    "async_add_event": "security_log",
    "async_clear_events": "security_log",
    "async_event_counts": "security_log",
    "tail_events": "security_log",
    "async_tail_events": "security_log",
}

__all__ = sorted(_ATTR_MODULES)

_loaded: Dict[str, ModuleType] = {}


def __getattr__(name: str) -> object:
    module_name = _ATTR_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = _loaded.get(module_name)
    if module is None:
        module = importlib.import_module(f".{module_name}", __name__)
        _loaded[module_name] = module
    value = getattr(module, name)
    globals()[name] = value
    return value
