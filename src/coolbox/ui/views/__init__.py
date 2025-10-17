"""Unified namespace for CoolBox views with structured subpackages."""
from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType

from .base import BaseDialog, BaseView, UIHelperMixin
from .dialogs import (
    AutoNetworkScanDialog,
    DefenderDialog,
    ExeInspectorDialog,
    FirewallDialog,
    ForceQuitDialog,
    QuickSettingsDialog,
    RecentFilesDialog,
    SecurityDialog,
    SystemInfoDialog,
)
from .overlays import ClickOverlay, OverlayState
from .screens import AboutView, HomeView, SettingsView, ToolsView

__all__ = [
    "BaseDialog",
    "BaseView",
    "UIHelperMixin",
    "AboutView",
    "HomeView",
    "SettingsView",
    "ToolsView",
    "ClickOverlay",
    "OverlayState",
    "AutoNetworkScanDialog",
    "ForceQuitDialog",
    "QuickSettingsDialog",
    "SystemInfoDialog",
    "RecentFilesDialog",
    "SecurityDialog",
    "FirewallDialog",
    "DefenderDialog",
    "ExeInspectorDialog",
]

# Maintain import compatibility for callers that still reference the previous
# flat module layout (e.g. ``coolbox.ui.views.force_quit_dialog``).
_legacy_modules: dict[str, ModuleType] = {
    "base_dialog": import_module(".base.base_dialog", __name__),
    "base_view": import_module(".base.base_view", __name__),
    "base_mixin": import_module(".base.base_mixin", __name__),
    "_fast_confidence": import_module(".base._fast_confidence", __name__),
    "about_view": import_module(".screens.about", __name__),
    "home_view": import_module(".screens.home", __name__),
    "settings_view": import_module(".screens.settings", __name__),
    "tools_view": import_module(".screens.tools", __name__),
    "quick_settings": import_module(".dialogs.quick_settings", __name__),
    "auto_scan_dialog": import_module(".dialogs.auto_scan", __name__),
    "force_quit_dialog": import_module(".dialogs.force_quit", __name__),
    "system_info_dialog": import_module(".dialogs.system_info", __name__),
    "recent_files_dialog": import_module(".dialogs.recent_files", __name__),
    "security_dialog": import_module(".dialogs.security", __name__),
    "firewall_dialog": import_module(".dialogs.firewall", __name__),
    "defender_dialog": import_module(".dialogs.defender", __name__),
    "exe_inspector_dialog": import_module(".dialogs.exe_inspector", __name__),
    "click_overlay": import_module(".overlays.click_overlay", __name__),
}

for name, module in _legacy_modules.items():
    sys.modules[f"{__name__}.{name}"] = module
