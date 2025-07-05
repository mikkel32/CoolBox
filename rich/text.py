"""Simple string subclass used as a placeholder for Rich Text."""

class Text:
    """Very small subset of :class:`rich.text.Text`."""

    def __init__(self, text: str = "", *, style: str | None = None) -> None:
        self.parts = [text]
        
    def append(self, text: str, *_, **__) -> None:  # pragma: no cover - simple
        self.parts.append(text)

    def stylize(self, *_, **__) -> None:  # pragma: no cover - noop
        pass

    def __str__(self) -> str:  # pragma: no cover - formatting
        return "".join(self.parts)
