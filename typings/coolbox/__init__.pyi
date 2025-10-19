from __future__ import annotations

from types import ModuleType
from typing import Sequence

class CoolBoxApp:
    def run(self) -> None: ...

def ensure_customtkinter(version: str = ...) -> ModuleType: ...

paths: ModuleType

__all__: Sequence[str]
