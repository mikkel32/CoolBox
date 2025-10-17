from __future__ import annotations


def adjust_color(color: str, factor: float) -> str:
    """Return *color* adjusted by *factor*."""
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        raise ValueError("invalid color format")

    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)

    factor = max(-1.0, min(1.0, factor))
    if factor >= 0:
        r = round(r + (255 - r) * factor)
        g = round(g + (255 - g) * factor)
        b = round(b + (255 - b) * factor)
    else:
        r = round(r * (1 + factor))
        g = round(g * (1 + factor))
        b = round(b * (1 + factor))

    return f"#{r:02x}{g:02x}{b:02x}"


def hex_brightness(color: str) -> float:
    """Return the perceptual brightness of *color* between 0 and 1."""
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        raise ValueError("invalid color format")

    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def lighten_color(color: str, factor: float) -> str:
    """Return *color* lightened by *factor* in the range ``0``-``1``."""
    return adjust_color(color, max(0.0, min(1.0, factor)))


def darken_color(color: str, factor: float) -> str:
    """Return *color* darkened by *factor* in the range ``0``-``1``."""
    return adjust_color(color, -max(0.0, min(1.0, factor)))


__all__ = [
    "adjust_color",
    "hex_brightness",
    "lighten_color",
    "darken_color",
]
