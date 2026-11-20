"""The Break Room -- hub screen. Pushed once after the splash/roster flow and returned to
after every shift/exam/plant-map/stats excursion (InspectorApp.pop_to_home() lands here).
Refreshes its numbers both on first mount and every time it becomes the active screen again,
so returning from a shift shows the new streak/mastery immediately.
"""
from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Digits, Static

from ...game import mastery, tracks
from ... import srs as srsmod


class HomeScreen(Screen):
    DEFAULT_CSS = """
    HomeScreen {
        align: center middle;
    }
    HomeScreen > Vertical {
        width: 64;
        height: auto;
        padding: 1 3;
    }
    HomeScreen #title {
        text-style: bold;
        color: #58a6ff;
        width: 100%;
        text-align: center;
    }
    HomeScreen #subtitle {
        color: #6e7681;
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }
    HomeScreen #streak-label {
        width: 100%;
        text-align: center;
        color: #6e7681;
        margin-top: 1;
    }
    HomeScreen #streak {
        width: 100%;
        text-align: center;
        color: #2ea043;
    }
    HomeScreen #best-streak {
        width: 100%;
        text-align: center;
        color: #6e7681;
        margin-bottom: 1;
    }
    HomeScreen .stat-line {
        width: 100%;
        text-align: center;
        margin-top: 0;
    }
    HomeScreen #module-line {
        width: 100%;
        text-align: center;
        color: #e3b341;
        margin-top: 1;
    }
    HomeScreen #unlocked-line {
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }
    HomeScreen #footer {
        width: 100%;
        text-align: center;
        color: #6e7681;
        margin-top: 2;
    }
    """

    BINDINGS = [
        Binding("s", "start_shift", "Start Shift"),
        Binding("m", "plant_map", "Plant Map"),
        Binding("e", "exam", "Exam"),
        Binding("t", "stats", "Stats"),
        Binding("p", "switch_profile", "Switch Profile"),
        Binding("b", "back_to_dashboard", "Dashboard"),
        Binding("escape", "back_to_dashboard", "Dashboard", show=False),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("INCIDENT ZERO -- BREAK ROOM", id="title")
            yield Static("", id="subtitle")
            yield Static("DAYS WITHOUT INCIDENT", id="streak-label")
            yield Digits("0", id="streak")
            yield Static("", id="best-streak")
            yield Static("", id="due-line", classes="stat-line")
            yield Static("", id="module-line")
            yield Static("", id="unlocked-line")
            yield Static(
                "[s] Start Shift   [m] Plant Map   [e] Exam   [t] Stats   "
                "[b] Dashboard   [p] Switch Profile   [q] Quit",
                id="footer",
            )

    def on_mount(self) -> None:
        self._refresh()

    def on_screen_resume(self) -> None:
        self._refresh()

    def _target_module_id(self) -> int:
        """The current/default module: state.current_module_id if set, else the lowest
        unlocked id of the current track (its first module is always unlocked)."""
        mid = self.app.state.current_module_id
        if mid is not None:
            return mid
        track = self.app.state.track
        unlocked = mastery.unlocked_modules(self.app.con, self.app.state.profile_id, track)
        return min(unlocked) if unlocked else (101 if track == "qaqc" else 1)

    def _refresh(self) -> None:
        profile_id = self.app.state.profile_id
        if profile_id is None:
            return
        con = self.app.con
        track = self.app.state.track

        row = con.execute(
            "SELECT name, days_without_incident, best_streak FROM profiles WHERE id=?",
            (profile_id,),
        ).fetchone()
        if row is None:
            return
        if track == "osha":
            streak, best = row["days_without_incident"], row["best_streak"]
        else:
            from ...game.rules import track_streak
            ts = track_streak(con, profile_id, track)
            streak, best = ts["days_without_incident"], ts["best_streak"]

        due_count = srsmod.due_count(con, profile_id, track)
        unlocked_count = len(mastery.unlocked_modules(con, profile_id, track))
        total = len(mastery.module_ids(con, track))
        module_id = self._target_module_id()

        title = "INCIDENT ZERO -- BREAK ROOM" if track == "osha" else "INCIDENT ZERO -- QA/QC BREAK ROOM"
        self.query_one("#title", Static).update(title)
        self.query_one("#subtitle", Static).update(
            f"Welcome back, {row['name']}   (track: {tracks.NAMES[track]})")
        self.query_one("#streak", Digits).update(str(streak))
        self.query_one("#best-streak", Static).update(f"Best streak: {best}")
        self.query_one("#due-line", Static).update(f"Reviews due: {due_count}")
        if track == "osha":
            module_line = f"Module {module_id}: {tracks.topic(module_id)}"
        else:
            module_line = f"Module {tracks.label(module_id)}: {tracks.topic(module_id)}"
        self.query_one("#module-line", Static).update(module_line)
        self.query_one("#unlocked-line", Static).update(f"{unlocked_count}/{total} modules unlocked")
        footer = ("[s] Start Shift   [m] Plant Map   [e] Exam   [t] Stats   "
                  "[b] Dashboard   [p] Switch Profile   [q] Quit")
        if track != "osha":
            footer = footer.replace("[e] Exam   ", "")
        self.query_one("#footer", Static).update(footer)

    def action_start_shift(self) -> None:
        self.app.show("shift", module_id=self._target_module_id())

    def action_plant_map(self) -> None:
        self.app.show("plantmap")

    def action_exam(self) -> None:
        if self.app.state.track != "osha":
            self.app.notify("The mock exam is the OSHA 30 exam -- QA/QC has no exam. "
                            "Switch track on the dashboard (k).", severity="warning")
            return
        if mastery.exam_unlocked(self.app.con, self.app.state.profile_id):
            self.app.show("exam")
        else:
            self.app.notify("Exam locks at 19/23 modules unlocked.", severity="warning")

    def action_stats(self) -> None:
        self.app.show("stats")

    def action_switch_profile(self) -> None:
        while len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        self.app.state.profile_id = None
        self.app.state.profile_name = None
        self.app.state.active_shift = None
        self.app.state.active_exam = None

    def action_back_to_dashboard(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.action_quit_app()
