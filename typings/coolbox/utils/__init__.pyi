from __future__ import annotations

from types import ModuleType
from typing import Any, Callable, Sequence

from coolbox.utils.__init__ import *
from coolbox.utils.display.theme import ThemeManager as ThemeManager, _ConfigLike as _ConfigLike
from coolbox.utils.display.ui import center_window as center_window, get_screen_refresh_rate as get_screen_refresh_rate
from coolbox.utils.files.cache import CacheItem as CacheItem, CacheManager as CacheManager
from coolbox.utils.files.file_manager import (
    FileManagerError as FileManagerError,
    atomic_write as atomic_write,
    atomic_write_bytes as atomic_write_bytes,
    copy_dir as copy_dir,
    copy_file as copy_file,
    delete_dir as delete_dir,
    delete_file as delete_file,
    ensure_dir as ensure_dir,
    list_files as list_files,
    move_dir as move_dir,
    move_file as move_file,
    pick_file as pick_file,
    read_bytes as read_bytes,
    read_json as read_json,
    read_lines as read_lines,
    read_text as read_text,
    touch_file as touch_file,
    write_bytes as write_bytes,
    write_json as write_json,
    write_lines as write_lines,
    write_text as write_text,
)
import coolbox.utils.file_manager as file_manager
import coolbox.utils.security as security
from coolbox.utils.network import (
    HTTPInfo as HTTPInfo,
    AutoScanInfo as AutoScanInfo,
    PortInfo as PortInfo,
    TOP_PORTS as TOP_PORTS,
    async_auto_scan as async_auto_scan,
    async_auto_scan_iter as async_auto_scan_iter,
    async_collect_http_info as async_collect_http_info,
    async_detect_local_hosts as async_detect_local_hosts,
    async_filter_active_hosts as async_filter_active_hosts,
    async_get_hostname as async_get_hostname,
    async_get_http_info as async_get_http_info,
    async_scan_host_list as async_scan_host_list,
    async_scan_hosts as async_scan_hosts,
    async_scan_hosts_detailed as async_scan_hosts_detailed,
    async_scan_hosts_iter as async_scan_hosts_iter,
    async_scan_port_list as async_scan_port_list,
    async_scan_ports as async_scan_ports,
    auto_scan_info_to_dict as auto_scan_info_to_dict,
    auto_scan_results_to_dict as auto_scan_results_to_dict,
    clear_arp_cache as clear_arp_cache,
    clear_dns_cache as clear_dns_cache,
    clear_host_cache as clear_host_cache,
    clear_http_cache as clear_http_cache,
    clear_local_host_cache as clear_local_host_cache,
    clear_ping_cache as clear_ping_cache,
    clear_scan_cache as clear_scan_cache,
    detect_arp_hosts as detect_arp_hosts,
    detect_local_hosts as detect_local_hosts,
    get_mac_address as get_mac_address,
    get_mac_vendor as get_mac_vendor,
    parse_hosts as parse_hosts,
    parse_port_range as parse_port_range,
    parse_ports as parse_ports,
    ports_as_range as ports_as_range,
    scan_port_list as scan_port_list,
    scan_ports as scan_ports,
    scan_targets as scan_targets,
    scan_targets_list as scan_targets_list,
)
from coolbox.utils.processes.cache import ProcessCache as ProcessCache
from coolbox.utils.processes.monitor import ProcessEntry as ProcessEntry, ProcessWatcher as ProcessWatcher
from coolbox.utils.processes.thread_manager import ThreadManager as ThreadManager
from coolbox.utils.processes.utils import (
    run_command as run_command,
    run_command_async as run_command_async,
    run_command_async_ex as run_command_async_ex,
    run_command_background as run_command_background,
    run_command_ex as run_command_ex,
)
from coolbox.utils.system import (
    console as console,
    get_system_info as get_system_info,
    get_system_metrics as get_system_metrics,
    open_path as open_path,
    run_with_spinner as run_with_spinner,
    slugify as slugify,
    strip_ansi as strip_ansi,
)
from coolbox.utils.system.hash_utils import (
    calc_data_hash as calc_data_hash,
    calc_hash as calc_hash,
    calc_hash_cached as calc_hash_cached,
    calc_hashes as calc_hashes,
)
from coolbox.utils.system.vm import launch_vm_debug as launch_vm_debug

__all__: Sequence[str]
__getattr__: Callable[[str], Any]
__dir__: Callable[[], list[str]]

# Re-export modules that behave like namespaces at runtime.
mouse_listener: ModuleType
defender: ModuleType
firewall: ModuleType
system_utils: ModuleType
window_utils: ModuleType

