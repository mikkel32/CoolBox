"""Public package interface for CoolBox."""

__version__ = "1.0.80"

import os

if not os.environ.get("COOLBOX_LIGHTWEIGHT"):
    from .app import CoolBoxApp  # noqa: F401
    from .ensure_deps import ensure_customtkinter  # noqa: F401

    __all__ = ["CoolBoxApp", "ensure_customtkinter"]
else:  # pragma: no cover - lightweight testing stubs
    class CoolBoxApp:
        """Minimal stub used when UI deps are unavailable."""

        def run(self) -> None:
            pass

    def ensure_customtkinter() -> None:
        return None

    __all__ = ["CoolBoxApp", "ensure_customtkinter"]
