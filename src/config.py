"""
Configuration management for CoolBox
"""
import json
import shutil
from pathlib import Path
from typing import Any, Dict

from .utils.helpers import log


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
            "window_height": 800,
            "auto_save": True,
            "recent_files": [],
            "max_recent_files": 10,
            "font_size": 14,
            "show_toolbar": True,
            "show_statusbar": True,
            "show_menu": True,
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
        }

        # Load configuration
        self.config = self._load_config()

    def ensure_dirs(self) -> None:
        """Create configuration and cache directories if needed."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        self.ensure_dirs()

        # Load existing config or use defaults
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded_config = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    return {**self.defaults, **loaded_config}
            except Exception as e:
                log(f"Error loading config: {e}")
                return self.defaults.copy()
        else:
            return self.defaults.copy()

    def save(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            log(f"Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """Set configuration value"""
        self.config[key] = value

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
