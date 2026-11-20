"""The Textual App shell: owns the shared DB connection, config, session state, and screen
navigation. Screens reach shared state via self.app.<attr> -- see ui/screens/*.py.

Screens are imported lazily by registry name so this module never hard-fails just because
one screen file has a bug -- the failure surfaces when that screen is actually opened.
"""
import importlib
from datetime import datetime, timezone
from textual.app import App

from .. import db, config

_SCREEN_MODULES = {
    "roster": ("osha_game.ui.screens.roster", "RosterScreen"),
    "splash": ("osha_game.ui.screens.splash", "SplashScreen"),
    "dashboard": ("osha_game.ui.screens.dashboard", "DashboardScreen"),
    "home": ("osha_game.ui.screens.home", "HomeScreen"),
    "lookup": ("osha_game.ui.screens.lookup", "LookupScreen"),
    "inspect": ("osha_game.ui.screens.inspect", "InspectScreen"),
    "interview": ("osha_game.ui.screens.interview", "InterviewScreen"),
    "plantmap": ("osha_game.ui.screens.plantmap", "PlantMapScreen"),
    "shift": ("osha_game.ui.screens.shift", "ShiftScreen"),
    "debrief": ("osha_game.ui.screens.debrief", "DebriefScreen"),
    "exam": ("osha_game.ui.screens.exam", "ExamScreen"),
    "examresults": ("osha_game.ui.screens.exam", "ExamResultsScreen"),
    "stats": ("osha_game.ui.screens.stats", "StatsScreen"),
}


def _screen_class(name: str):
    mod_name, cls_name = _SCREEN_MODULES[name]
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


class GameState:
    """Session-lived state, reset whenever the player switches profiles."""

    def __init__(self):
        self.profile_id: int | None = None
        self.profile_name: str | None = None
        self.active_shift = None       # a game.rules.Shift while a shift is in progress
        self.active_exam = None        # a game.rules.Exam while an exam is in progress
        self.track: str = "osha"       # 'osha' or 'qaqc'; picked on the dashboard (k)
        self._module_by_track: dict[str, int | None] = {}

    @property
    def current_module_id(self) -> int | None:
        """Last module picked on the plant map, remembered per track."""
        return self._module_by_track.get(self.track)

    @current_module_id.setter
    def current_module_id(self, value: int | None) -> None:
        self._module_by_track[self.track] = value


class InspectorApp(App):
    CSS_PATH = "styles.tcss"
    TITLE = "INCIDENT ZERO"
    SUB_TITLE = "OSHA 30 dashboard"
    BINDINGS = [("ctrl+q", "quit_app", "Quit")]

    def __init__(self):
        super().__init__()
        self.con = db.game_connect()
        self.cfg = config.load()
        self.state = GameState()

    def on_mount(self) -> None:
        self.push_screen(_screen_class("roster")())

    def show(self, name: str, **kwargs):
        """Push a new screen by registry name (see _SCREEN_MODULES)."""
        return self.push_screen(_screen_class(name)(**kwargs))

    def pop_to_home(self) -> None:
        """Collapse the screen stack back down to the break-room home screen, from anywhere."""
        home_cls = _screen_class("home")
        while len(self.screen_stack) > 1:
            if isinstance(self.screen, home_cls):
                return
            self.pop_screen()
        if not isinstance(self.screen, home_cls):
            self.push_screen(home_cls())

    def action_quit_app(self) -> None:
        self.con.close()
        self.exit()

    def touch_profile(self) -> None:
        if self.state.profile_id is not None:
            self.con.execute(
                "UPDATE profiles SET last_seen_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), self.state.profile_id),
            )
            self.con.commit()


def run() -> None:
    InspectorApp().run()
