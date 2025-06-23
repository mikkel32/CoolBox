"""Simple application state model."""

from dataclasses import dataclass


@dataclass
class AppState:
    current_view: str = "home"
