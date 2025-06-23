"""
Configuration management for CoolBox
"""
import json
from pathlib import Path
from typing import Any, Dict


class Config:
    """Application configuration manager"""

    def __init__(self):
        """Initialize configuration"""
        self.config_dir = Path.home() / ".coolbox"
        self.config_file = self.config_dir / "config.json"

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
            "theme": {
                "primary_color": "#1f538d",
                "secondary_color": "#212121",
                "accent_color": "#007acc",
                "text_color": "#ffffff",
                "background_color": "#1e1e1e",
            },
        }

        # Load configuration
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(exist_ok=True)

        # Load existing config or use defaults
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded_config = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    return {**self.defaults, **loaded_config}
            except Exception as e:
                print(f"Error loading config: {e}")
                return self.defaults.copy()
        else:
            return self.defaults.copy()

    def save(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

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

    def reset_to_defaults(self):
        """Reset configuration to defaults"""
        self.config = self.defaults.copy()
        self.save()
