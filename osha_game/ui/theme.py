"""Palette, glyphs, and small color helpers shared by every screen and effect.
Colors only, unicode shapes only -- no emoji, per house style."""
import colorsys

BG = "#0d1117"
PANEL = "#161b22"
PANEL_ALT = "#1c2129"
TEXT = "#c9d1d9"
MUTED = "#6e7681"
SAFE = "#2ea043"
WARN = "#d29922"
DANGER = "#da3633"
INFO = "#58a6ff"
GOLD = "#e3b341"  # confidence-bet accent

# Plant-map mastery bands, dim -> bright (keys match game.mastery.band_for()'s return values)
BAND_COLOR = {
    "locked": "#30363d",
    "weak": "#8b3a3a",
    "shaky": "#b5762b",
    "solid": "#8a8f1f",
    "strong": "#2ea043",
}

GLYPH = {
    "tile": "■",
    "tile_small": "▪",
    "locked": "▲",
    "clean": "✓",
    "incident": "✕",
    "bet": "§",
    "arrow": "▸",
    "dot": "●",
}


def hsv_hex(h: float, s: float = 0.75, v: float = 0.95) -> str:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def rainbow_stops(n: int, s: float = 0.75, v: float = 0.95) -> list[str]:
    return [hsv_hex(i / max(n, 1), s, v) for i in range(n)]
