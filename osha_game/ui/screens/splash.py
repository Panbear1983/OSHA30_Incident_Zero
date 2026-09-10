"""SplashScreen -- the brief "clocking in" animation shown right after a profile is picked
in RosterScreen, before HomeScreen. Pure presentation: no DB access, no game state changes."""
import pyfiglet
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from .. import fx

_TITLE_TEXT = "INCIDENT ZERO"
_MAX_LINE_WIDTH = 100


class SplashScreen(Screen):
    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
    }
    SplashScreen > Vertical {
        width: auto;
        height: auto;
    }
    SplashScreen .figlet-line {
        width: auto;
        height: 1;
    }
    SplashScreen .plain-title {
        width: auto;
        text-style: bold;
        color: #c9d1d9;
        text-align: center;
        margin-bottom: 1;
    }
    SplashScreen .clocking-in {
        width: auto;
        color: #c9d1d9;
        text-align: center;
        margin-top: 1;
    }
    SplashScreen .press-any-key {
        width: auto;
        color: #6e7681;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._advanced = False

    def compose(self) -> ComposeResult:
        animations = self.app.cfg["ui"]["animations"]
        with Vertical():
            if animations:
                lines = self._figlet_lines()
                if lines is None:
                    yield Static(_TITLE_TEXT, classes="plain-title")
                else:
                    fps = self.app.cfg["ui"]["fps"]
                    for line in lines:
                        yield fx.RainbowTitle(line, fps=fps, animate=True, classes="figlet-line")
            else:
                yield Static(_TITLE_TEXT, classes="plain-title")
            yield Static(
                f"Clocking in, {self.app.state.profile_name}...", classes="clocking-in"
            )
            yield Static("-- press any key --", classes="press-any-key")

    def _figlet_lines(self) -> list[str] | None:
        """Render the figlet title and split it into non-blank lines, degrading fonts (and
        finally to None, meaning "give up, use the plain Static") if a line is too wide for
        a narrow terminal to ever show sanely."""
        for font in ("slant", "small"):
            try:
                rendered = pyfiglet.figlet_format(_TITLE_TEXT, font=font)
            except Exception:
                continue
            lines = [ln for ln in rendered.splitlines() if ln.strip()]
            if lines and max(len(ln) for ln in lines) <= _MAX_LINE_WIDTH:
                return lines
        return None

    def on_mount(self) -> None:
        delay = 2.5 if self.app.cfg["ui"]["animations"] else 1.0
        self.set_timer(delay, self._advance)

    def on_key(self, event) -> None:
        self._advance()

    def _advance(self) -> None:
        if self._advanced:
            return
        self._advanced = True
        self.app.pop_screen()
        self.app.show("home")
