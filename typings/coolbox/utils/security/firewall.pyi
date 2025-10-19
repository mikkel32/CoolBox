from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol, Sequence


class MacFirewallTooling:
    defaults_path: Path | None
    socketfilterfw_path: Path | None
    defaults_usable: bool
    socketfilterfw_usable: bool
    defaults_plist_path: Path | None
    defaults_plist_readable: bool
    defaults_plist_writable: bool
    defaults_plist_bootstrap_supported: bool
    defaults_plist_bootstrap_error: str | None
    defaults_plist_damaged: bool
    defaults_plist_parse_error: str | None
    launchctl_path: Path | None
    launchctl_usable: bool
    launchctl_label_path: Path | None
    launchctl_label_available: bool
    launchctl_supports_kickstart: bool
    launchctl_errors: tuple[str, ...]
    errors: tuple[str, ...]

    def __init__(
        self,
        defaults_path: Path | None,
        socketfilterfw_path: Path | None,
        defaults_usable: bool,
        socketfilterfw_usable: bool,
        defaults_plist_path: Path | None,
        defaults_plist_readable: bool,
        defaults_plist_writable: bool,
        defaults_plist_bootstrap_supported: bool,
        defaults_plist_bootstrap_error: str | None,
        defaults_plist_damaged: bool,
        defaults_plist_parse_error: str | None,
        launchctl_path: Path | None,
        launchctl_usable: bool,
        launchctl_label_path: Path | None,
        launchctl_label_available: bool,
        launchctl_supports_kickstart: bool,
        launchctl_errors: tuple[str, ...],
        errors: tuple[str, ...],
    ) -> None: ...


class FirewallStatus:
    domain: bool | None
    private: bool | None
    public: bool | None
    services_ok: bool
    cmdlets_available: bool
    policy_lock: bool
    third_party_firewall: bool
    services_error: str | None
    error: str | None
    third_party_names: tuple[str, ...]
    stealth_mode: bool | None
    block_all: bool | None
    allows_signed: bool | None
    mac_global_state: int | None
    mac_defaults_available: bool | None
    mac_socketfilterfw_available: bool | None
    mac_admin: bool | None
    mac_defaults_usable: bool | None
    mac_socketfilterfw_usable: bool | None
    mac_defaults_plist_available: bool | None
    mac_defaults_plist_readable: bool | None
    mac_defaults_plist_writable: bool | None
    mac_defaults_plist_bootstrap_supported: bool | None
    mac_defaults_plist_bootstrap_error: str | None
    mac_defaults_plist_damaged: bool | None
    mac_defaults_plist_parse_error: str | None
    mac_launchctl_available: bool | None
    mac_launchctl_usable: bool | None
    mac_launchctl_label_available: bool | None
    mac_launchctl_kickstart_supported: bool | None
    mac_launchctl_errors: tuple[str, ...]
    mac_tool_errors: tuple[str, ...]


_MAC_PLIST_BOOTSTRAP_TEMPLATE: Mapping[str, int]


class _CachedPlistReader(Protocol):
    def __call__(self) -> tuple[dict[str, object] | None, str | None]: ...

    def cache_clear(self) -> None: ...


class _CachedTooling(Protocol):
    def __call__(self) -> MacFirewallTooling: ...

    def cache_clear(self) -> None: ...


def _mac_tooling(refresh: bool = ...) -> MacFirewallTooling: ...

_mac_detect_tooling_cached: _CachedTooling

_mac_defaults_plist_cached: _CachedPlistReader

def _mac_defaults_plist_value(key: str) -> tuple[int | None, str | None]: ...

def _mac_defaults_plist_write(
    key: str,
    value: int,
    tooling: MacFirewallTooling | None = ...,
) -> str | None: ...

def _mac_defaults_plist_bootstrap(payload: Mapping[str, int]) -> str | None: ...

def _mac_defaults_read_int(key: str) -> tuple[int | None, str | None]: ...

def _mac_defaults_write_int(key: str, value: int) -> str | None: ...

def _mac_query_socketfilterfw(flag: str) -> tuple[bool | None, str | None]: ...

def _mac_firewall_global_state(
    tooling: MacFirewallTooling | None = ...,
) -> tuple[bool | None, int | None, str | None]: ...

def _mac_set_firewall_enabled(enabled: bool) -> tuple[bool, str | None]: ...

def _run_ex(cmd: Sequence[str], timeout: float = ...) -> tuple[str, int]: ...

def is_firewall_supported() -> bool: ...

def is_firewall_enabled() -> bool | None: ...

def get_firewall_status() -> FirewallStatus: ...

def set_firewall_enabled(enabled: bool) -> tuple[bool, str | None]: ...

def ensure_admin() -> bool: ...
