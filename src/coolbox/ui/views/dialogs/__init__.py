"""Dialog views used throughout the CoolBox UI."""
from __future__ import annotations

from .auto_scan import AutoNetworkScanDialog
from .defender import DefenderDialog
from .exe_inspector import ExeInspectorDialog
from .firewall import FirewallDialog
from .force_quit import ForceQuitDialog
from .quick_settings import QuickSettingsDialog
from .recent_files import RecentFilesDialog
from .security import SecurityDialog
from .system_info import SystemInfoDialog

__all__ = [
    "AutoNetworkScanDialog",
    "DefenderDialog",
    "ExeInspectorDialog",
    "FirewallDialog",
    "ForceQuitDialog",
    "QuickSettingsDialog",
    "RecentFilesDialog",
    "SecurityDialog",
    "SystemInfoDialog",
]
