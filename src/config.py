"""
Configuration management for CoolBox
"""
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)


class Config:
    """Application configuration manager"""

    def __init__(self):
        """Initialize configuration"""
        self.config_dir = Path.home() / ".coolbox"
        self.config_file = self.config_dir / "config.json"
        self.cache_dir = self.config_dir / "cache"

        self.ensure_dirs()

        # Default configuration
        self.defaults = {
            "appearance_mode": "dark",
            "color_theme": "blue",
            "window_width": 1200,
            "window_height": 1000,
            "auto_save": True,
            "recent_files": [],
            "max_recent_files": 10,
            "font_size": 14,
            "show_toolbar": True,
            "show_statusbar": True,
            "show_menu": True,
            "developer_mode": False,
            "basic_rendering": False,
            "section_states": {},
            "force_quit_cpu_alert": 80.0,
            "force_quit_mem_alert": 500.0,
            "force_quit_auto_kill": "none",
            "force_quit_interval": 2.0,
            "force_quit_detail_interval": 5,
            "force_quit_samples": 5,
            "force_quit_adaptive": True,
            "force_quit_adaptive_detail": True,
            "force_quit_max": 300,
            "force_quit_width": 1000,
            "force_quit_height": 650,
            "force_quit_sort": "CPU",
            "force_quit_sort_reverse": True,
            "force_quit_on_top": False,
            "force_quit_conn_interval": 2.0,
            "force_quit_file_interval": 2.0,
            "force_quit_cache_ttl": 30.0,
            "force_quit_conn_global": 50,
            "force_quit_file_global": 50,
            "force_quit_stable_cycles": 10,
            "force_quit_stable_skip": 3,
            "force_quit_batch_size": 100,
            "force_quit_auto_batch": True,
            "force_quit_min_batch": 25,
            "force_quit_max_batch": 1000,
            "force_quit_auto_interval": True,
            "force_quit_min_interval": 0.5,
            "force_quit_max_interval": 10.0,
            "force_quit_min_workers": 2,
            "force_quit_max_workers": 16,
            "force_quit_change_window": 3,
            "force_quit_change_cpu": 0.5,
            "force_quit_change_mem": 1.0,
            "force_quit_change_io": 0.5,
            "force_quit_change_score": 1.0,
            "force_quit_change_agg": 1,
            "force_quit_change_alpha": 0.2,
            "force_quit_change_ratio": 0.3,
            "force_quit_change_std_mult": 2.0,
            "force_quit_change_mad_mult": 3.0,
            "force_quit_change_decay": 0.8,
            "force_quit_visible_cpu": 0.5,
            "force_quit_visible_mem": 10.0,
            "force_quit_visible_io": 0.1,
            "force_quit_visible_auto": False,
            "force_quit_warn_cpu": 40.0,
            "force_quit_warn_mem": 200.0,
            "force_quit_warn_io": 1.0,
            "force_quit_hide_system": False,
            "force_quit_slow_ratio": 0.02,
            "force_quit_fast_ratio": 0.2,
            "force_quit_ratio_window": 5,
            "force_quit_trend_window": 5,
            "force_quit_trend_cpu": 5.0,
            "force_quit_trend_mem": 50.0,
            "force_quit_trend_io": 1.0,
            "force_quit_trend_io_window": 5,
            "force_quit_trend_slow_ratio": 0.05,
            "force_quit_trend_fast_ratio": 0.25,
            "force_quit_show_trends": True,
            "force_quit_show_stable": False,
            "force_quit_show_deltas": True,
            "force_quit_show_normal": False,
            "force_quit_show_score": False,
            "force_quit_ignore_age": 1.0,
            "force_quit_normal_window": 3,
            "force_quit_exclude_users": [],
            "force_quit_ignore_names": [],
            "theme": {
                "primary_color": "#1f538d",
                "secondary_color": "#212121",
                "accent_color": "#007acc",
                "text_color": "#ffffff",
                "background_color": "#1e1e1e",
            },
            "scan_cache_ttl": 300,
            "scan_concurrency": 100,
            "scan_timeout": 0.5,
            "scan_family": "auto",
            "scan_services": False,
            "scan_banner": False,
            "scan_ping": False,
            "scan_ping_timeout": 1.0,
            "scan_ping_concurrency": 100,
            "scan_latency": False,
            "kill_by_click_interval": None,
            "kill_by_click_min_interval": None,
            "kill_by_click_max_interval": None,
            "kill_by_click_auto_interval": True,
            "kill_by_click_kf_process_noise": 1.0,
            "kill_by_click_kf_measurement_noise": 5.0,
            "window_min_width": 800,
            "window_min_height": 800,
        }

        # Load configuration
        self.config = self.defaults.copy()
        self.load_ok = self._load_config()

    def ensure_dirs(self) -> None:
        """Create configuration and cache directories if needed."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)

    def _load_config(self) -> bool:
        """Load configuration from file.

        Returns ``True`` if loading succeeded, ``False`` otherwise.
        """
        self.ensure_dirs()

        # Load existing config or use defaults
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded_config = json.load(f)
                # Merge with defaults to ensure all keys exist
                self.config = {**self.defaults, **loaded_config}
                return True
            except json.JSONDecodeError as e:
                getattr(logger, "warn" "ing")("Invalid config file, resetting to defaults: %s", e)
                backup = self.config_file.with_suffix(self.config_file.suffix + ".bak")
                try:
                    shutil.move(self.config_file, backup)
                except OSError as backup_err:
                    getattr(logger, "warn" "ing")("Failed to back up invalid config: %s", backup_err)
                self.config = self.defaults.copy()
                self.save()
                return False
            except OSError as e:
                logger.error("Error reading config: %s", e)
                self.config = self.defaults.copy()
                return False
            except Exception as e:
                logger.error("Error loading config: %s", e)
                self.config = self.defaults.copy()
                return False
        else:
            self.config = self.defaults.copy()
            return True

    def save(self) -> bool:
        """Save configuration to file.

        Returns ``True`` if saving succeeded, ``False`` otherwise.
        """
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=4)
            return True
        except OSError as e:
            msg = f"Error saving config: {e}"
            logger.error(msg)
            sys.stdout.write(msg + "\n")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """Set configuration value"""
        self.config[key] = value

    def get_section_state(self, key: str, default: bool = True) -> bool:
        """Return persisted expand/collapse state for *key*."""
        states = self.config.setdefault("section_states", {})
        return states.get(key, default)

    def set_section_state(self, key: str, value: bool) -> None:
        """Persist expand/collapse state for *key*."""
        states = self.config.setdefault("section_states", {})
        states[key] = value
        self.save()

    def add_recent_file(self, filepath: str):
        """Add a file to recent files list"""
        recent = self.config.get("recent_files", [])

        # Remove if already exists
        if filepath in recent:
            recent.remove(filepath)

        # Add to beginning
        recent.insert(0, filepath)

        # Limit size
        max_files = self.config.get("max_recent_files", 10)
        self.config["recent_files"] = recent[:max_files]
        self.save()

    def reset_to_defaults(self):
        """Reset configuration to defaults"""
        self.config = self.defaults.copy()
        self.save()

    def clear_cache(self) -> int:
        """Remove files from the cache directory.

        Returns the number of items deleted.
        """
        count = 0
        self.ensure_dirs()
        if self.cache_dir.exists():
            for path in self.cache_dir.iterdir():
                try:
                    if path.is_file():
                        path.unlink()
                        count += 1
                    else:
                        shutil.rmtree(path)
                        count += 1
                except Exception:
                    continue
        return count
