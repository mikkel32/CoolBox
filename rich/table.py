"""Very small table implementation."""

from __future__ import annotations

from typing import List


class Table:
    def __init__(self, *headers: str, title: str | None = None, expand: bool = False) -> None:
        self.headers = list(headers)
        self.rows: List[List[str]] = []
        self.title = title
        self.expand = expand

    @classmethod
    def grid(cls) -> "Table":  # pragma: no cover - simple helper
        return cls()

    def add_column(self, header: str = "", *, justify: str | None = None) -> None:
        self.headers.append(header)

    def add_row(self, *values: str) -> None:
        self.rows.append(list(values))

    def __str__(self) -> str:  # pragma: no cover - formatting
        table = []
        if self.headers:
            table.append(" | ".join(self.headers))
            table.append("-+-".join("-" * len(h) for h in self.headers))
        for row in self.rows:
            table.append(" | ".join(row))
        return "\n".join(table)


__all__ = ["Table"]
