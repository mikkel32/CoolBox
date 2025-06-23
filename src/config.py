"""Application configuration settings."""

from dataclasses import dataclass

@dataclass
class Config:
    title: str = "CoolBox"
    width: int = 800
    height: int = 600

    @property
    def geometry(self) -> str:
        return f"{self.width}x{self.height}"
