"""Small native visual effects -- deliberately no external effects library (a compat risk
against the pinned Textual 7.5 API). Everything here is timer-driven Rich/Textual, nothing
more. Screens that want a flash or a rainbow import from here rather than reinventing it."""
from rich.text import Text
from textual.widgets import Static
from . import theme


class RainbowTitle(Static):
    """A line of text whose per-character hue cycles. Pass animate=False (screens should
    wire this to the app's config [ui].animations) to render a static rainbow instead."""

    def __init__(self, text: str, *, fps: int = 10, animate: bool = True, **kwargs):
        super().__init__(**kwargs)
        self._text = text
        self._phase = 0.0
        self._fps = max(1, fps)
        self._animate = animate
        self._timer = None

    def on_mount(self) -> None:
        self._render_frame()
        if self._animate:
            self._timer = self.set_interval(1 / self._fps, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.02) % 1.0
        self._render_frame()

    def _render_frame(self) -> None:
        n = max(len(self._text), 1)
        out = Text()
        for i, ch in enumerate(self._text):
            hue = (self._phase + i / n) % 1.0
            out.append(ch, style=theme.hsv_hex(hue))
        self.update(out)

    def set_text(self, text: str) -> None:
        self._text = text
        self._render_frame()


def flash(widget, css_class: str, seconds: float = 0.3) -> None:
    """Add a CSS class, then remove it after `seconds` -- the right/wrong answer flash."""
    widget.add_class(css_class)
    widget.set_timer(seconds, lambda: widget.remove_class(css_class))
