"""RosterScreen -- the very first screen. Lists existing profiles, lets the player pick one,
create a new one, or delete one. Pushed exactly once by InspectorApp.on_mount() and always
sits at the base of the screen stack (index 0)."""
import sqlite3
from datetime import datetime, timezone

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .. import theme
from ..fx import RainbowTitle
from .modal import TypedConfirmModal

_PROFILES_QUERY = (
    "SELECT id, name, days_without_incident, best_streak, last_seen_at FROM profiles "
    "ORDER BY (last_seen_at IS NULL), last_seen_at DESC"
)


class RosterScreen(Screen):
    """Crew roster: pick an inspector to clock in as, add a new one, or delete one."""

    DEFAULT_CSS = f"""
    RosterScreen {{
        align: center middle;
    }}

    RosterScreen > #root {{
        width: 80;
        height: auto;
        max-height: 90%;
        padding: 1 2;
    }}

    RosterScreen #title {{
        height: 1;
        text-align: center;
        margin-bottom: 1;
    }}

    RosterScreen #subtitle {{
        color: {theme.MUTED};
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }}

    RosterScreen #roster-list {{
        height: 14;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
    }}

    RosterScreen #empty-state {{
        height: 14;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
        color: {theme.MUTED};
        content-align: center middle;
        text-align: center;
        padding: 0 4;
    }}

    RosterScreen #new-profile {{
        height: auto;
        border: heavy {theme.GOLD};
        background: {theme.PANEL};
        padding: 1 2;
        margin-top: 1;
    }}

    RosterScreen #new-profile-label {{
        color: {theme.TEXT};
        margin-bottom: 1;
    }}

    RosterScreen #hint {{
        color: {theme.MUTED};
        margin-top: 1;
        text-align: center;
    }}

    RosterScreen .hidden {{
        display: none;
    }}
    """

    BINDINGS = [
        Binding("n", "new_profile", "New", show=True),
        Binding("x", "delete_profile", "Delete", show=True),
        Binding("q", "quit_app", "Quit", show=True),
        Binding("escape", "cancel_new", "Cancel", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._profile_by_id: dict[int, sqlite3.Row] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield RainbowTitle(
                "INCIDENT ZERO",
                animate=self.app.cfg["ui"]["animations"],
                id="title",
            )
            yield Static("Crew Roster", id="subtitle")
            yield OptionList(id="roster-list")
            yield Static(
                "No inspectors on the roster yet. Press n to add one.",
                id="empty-state",
                classes="hidden",
            )
            with Vertical(id="new-profile", classes="hidden"):
                yield Static(
                    "New inspector name -- enter to confirm, escape to cancel:",
                    id="new-profile-label",
                )
                yield Input(placeholder="Inspector name", id="new-name")
            yield Static(
                f"{theme.GLYPH['arrow']} enter=clock in   n=new   x=delete   q=quit",
                id="hint",
            )

    def on_mount(self) -> None:
        self._refresh_list()

    # -- data -----------------------------------------------------------------

    @staticmethod
    def _profile_text(row: sqlite3.Row) -> Text:
        name = row["name"]
        streak = row["days_without_incident"]
        best = row["best_streak"]
        return Text(f"{name:<20} streak {streak:>3}  best {best:>3}")

    def _refresh_list(self) -> None:
        rows = self.app.con.execute(_PROFILES_QUERY).fetchall()
        self._profile_by_id = {row["id"]: row for row in rows}

        option_list = self.query_one("#roster-list", OptionList)
        empty_state = self.query_one("#empty-state", Static)
        option_list.clear_options()

        if rows:
            for row in rows:
                option_list.add_option(Option(self._profile_text(row), id=str(row["id"])))
            option_list.highlighted = 0
            option_list.remove_class("hidden")
            empty_state.add_class("hidden")
            option_list.focus()
        else:
            option_list.add_class("hidden")
            empty_state.remove_class("hidden")

    # -- pick profile (enter) --------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "roster-list" or event.option_id is None:
            return
        row = self._profile_by_id.get(int(event.option_id))
        if row is None:
            return
        self.app.state.profile_id = row["id"]
        self.app.state.profile_name = row["name"]
        self.app.touch_profile()
        self.app.show("splash")

    # -- new profile (n) --------------------------------------------------------

    def action_new_profile(self) -> None:
        self._set_new_profile_visible(True)

    def action_cancel_new(self) -> None:
        new_profile = self.query_one("#new-profile")
        if "hidden" not in new_profile.classes:
            self._set_new_profile_visible(False)

    def _set_new_profile_visible(self, visible: bool) -> None:
        new_profile = self.query_one("#new-profile")
        name_input = self.query_one("#new-name", Input)
        if visible:
            new_profile.remove_class("hidden")
            name_input.value = ""
            name_input.focus()
        else:
            new_profile.add_class("hidden")
            name_input.value = ""
            option_list = self.query_one("#roster-list", OptionList)
            if option_list.option_count:
                option_list.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "new-name":
            return
        name = event.value.strip()
        if not name:
            self.app.notify("Enter a name first.", severity="warning")
            return
        try:
            self.app.con.execute(
                "INSERT INTO profiles (name, created_at) VALUES (?, ?)",
                (name, datetime.now(timezone.utc).isoformat()),
            )
            self.app.con.commit()
        except sqlite3.IntegrityError:
            self.app.notify(f"{name!r} is already taken.", severity="warning")
            return
        self.app.notify(f"Added {name} to the roster.")
        self._set_new_profile_visible(False)
        self._refresh_list()

    # -- delete profile (x) ------------------------------------------------------

    @work
    async def action_delete_profile(self) -> None:
        option_list = self.query_one("#roster-list", OptionList)
        if option_list.option_count == 0 or option_list.highlighted is None:
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        if option.id is None:
            return
        row = self._profile_by_id.get(int(option.id))
        if row is None:
            return
        name = row["name"]
        confirmed = await self.app.push_screen_wait(
            TypedConfirmModal(
                f"Type {name!r} to permanently delete this profile and all its progress.",
                name,
            )
        )
        if confirmed:
            self.app.con.execute("DELETE FROM profiles WHERE id=?", (row["id"],))
            self.app.con.commit()
            self.app.notify(f"Removed {name}.")
            self._refresh_list()

    # -- quit (q) -----------------------------------------------------------------

    def action_quit_app(self) -> None:
        self.app.action_quit_app()
