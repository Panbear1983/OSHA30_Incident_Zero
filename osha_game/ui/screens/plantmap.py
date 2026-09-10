"""Plant map: a 5x5 grid of the 23 module tiles, colored by mastery band. Pressing an
unlocked tile jumps straight into a shift for that module."""
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import Screen
from textual.widgets import Button, Static

from .. import theme
from ...game import mastery
from ...content.segment import TOPICS


class PlantMapScreen(Screen):
    DEFAULT_CSS = """
    PlantMapScreen {
        align: center middle;
    }
    PlantMapScreen > Static.title {
        dock: top;
        height: 1;
        content-align: center middle;
        color: #58a6ff;
        text-style: bold;
        margin-top: 1;
    }
    Grid {
        grid-size: 5 5;
        grid-gutter: 1 1;
        width: auto;
        height: auto;
        padding: 1 2;
    }
    Grid Button {
        width: 17;
        height: 5;
        color: #c9d1d9;
    }
    Grid Button:disabled {
        color: #6e7681;
    }
    """

    BINDINGS = [("escape", "close_map", "Back")]

    def __init__(self):
        super().__init__()
        self._module_ids: list[int] = []

    def compose(self) -> ComposeResult:
        yield Static("PLANT MAP", classes="title")
        yield Grid()

    def on_mount(self) -> None:
        con = self.app.con
        profile_id = self.app.state.profile_id
        self._module_ids = [
            r["id"] for r in con.execute("SELECT id FROM bank.modules ORDER BY id").fetchall()
        ]

        grid = self.query_one(Grid)
        for mod_id in self._module_ids:
            pct = mastery.module_mastery(con, profile_id, mod_id)
            unlocked = mastery.module_unlocked(con, profile_id, mod_id)
            band = mastery.band_for(pct, locked=not unlocked)
            color = theme.BAND_COLOR[band]

            topic = TOPICS.get(mod_id, f"Module {mod_id}")
            status = "LOCKED" if not unlocked else f"{pct:.0f}%"
            label = Text(f"M{mod_id:02d}\n{topic}\n{status}", justify="center")

            btn = Button(label, id=f"tile-{mod_id}", disabled=not unlocked)
            btn.styles.background = color
            grid.mount(btn)

        # Focus the first enabled tile so keyboard nav has somewhere to start.
        for mod_id in self._module_ids:
            btn = self.query_one(f"#tile-{mod_id}", Button)
            if not btn.disabled:
                btn.focus()
                break

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.disabled:
            return
        mod_id = int(event.button.id.split("-")[1])
        self.app.state.current_module_id = mod_id
        self.app.pop_screen()
        self.app.show("shift", module_id=mod_id)

    def action_close_map(self) -> None:
        self.app.pop_screen()

    def key_left(self) -> None:
        self.focus_previous()

    def key_right(self) -> None:
        self.focus_next()

    def key_up(self) -> None:
        self.focus_previous()

    def key_down(self) -> None:
        self.focus_next()
