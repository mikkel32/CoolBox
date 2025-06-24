"""Public package interface for CoolBox."""

from .app import CoolBoxApp
from .ensure_deps import ensure_customtkinter

__all__ = ["CoolBoxApp", "ensure_customtkinter"]
