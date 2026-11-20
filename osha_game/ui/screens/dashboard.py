"""The four doors. Pushed right after the splash, above the roster and below everything
else. Each door answers one kind of question and nothing else (see PLAN.md):

  Train      Do I remember this one fact?          (the game; the only scored door)
  Look Up    What is the rule / number / standard?  (search, no scoring)
  Inspect    Did I check everything for module N?   (fixed walk, ticks, Word/PDF export)
  Interview  Can I explain what I'd do?             (open scenario, self-rated only)
"""
from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from .. import theme
from ..fx import RainbowTitle
from ...game import tracks

DOORS = (
    ("1", "TRAIN", "the inspection game: shifts, plant map, exam, stats", "home"),
    ("2", "LOOK UP", "find a rule, number, standard, or term, with its page", "lookup"),
    ("3", "INSPECT", "walk a module's checklist; export it as Word / PDF", "inspect"),
    ("4", "INTERVIEW", "talk through a scenario, then compare with the guide", "interview"),
)
# What the doors say while the QA/QC track is picked (Interview stays OSHA-only).
QAQC_BLURBS = {
    "home": "QA/QC shifts on six modules, same FSRS reviews; no exam",
    "lookup": "glossary (English / 繁體中文) and key numbers, with sources",
    "inspect": "QA/QC checklists: cable pull, reel, fiber, Cat6, NCR; Word / PDF",
    "interview": "OSHA scenarios only (this door has no QA/QC content)",
}


class DashboardScreen(Screen):
    DEFAULT_CSS = f"""
    DashboardScreen {{
        align: center middle;
    }}
    DashboardScreen > Vertical {{
        width: 86;
        height: auto;
        padding: 1 3;
    }}
    DashboardScreen #title {{
        height: 1;
        text-align: center;
        margin-bottom: 1;
    }}
    DashboardScreen #welcome {{
        color: {theme.MUTED};
        text-align: center;
        margin-bottom: 1;
    }}
    DashboardScreen #track {{
        text-align: center;
        margin-bottom: 1;
    }}
    DashboardScreen .door {{
        height: 3;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
        padding: 0 2;
        margin-bottom: 0;
    }}
    DashboardScreen #glance {{
        color: {theme.MUTED};
        text-align: center;
        margin-top: 1;
    }}
    DashboardScreen #footer {{
        color: {theme.MUTED};
        text-align: center;
        margin-top: 1;
    }}
    """

    BINDINGS = [
        Binding("1", "door('home')", "Train", show=False),
        Binding("t", "door('home')", "Train", show=True),
        Binding("2", "door('lookup')", "Look Up", show=False),
        Binding("l", "door('lookup')", "Look Up", show=True),
        Binding("3", "door('inspect')", "Inspect", show=False),
        Binding("i", "door('inspect')", "Inspect", show=True),
        Binding("4", "door('interview')", "Interview", show=False),
        Binding("v", "door('interview')", "Interview", show=True),
        Binding("k", "switch_track", "Switch Track", show=True),
        Binding("p", "switch_profile", "Switch Profile", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RainbowTitle("INCIDENT ZERO", animate=self.app.cfg["ui"]["animations"], id="title")
            yield Static("", id="welcome")
            yield Static("", id="track")
            for key, name, blurb, screen in DOORS:
                yield Static(self._door_text(key, name, blurb), classes="door", id=f"door-{screen}")
            yield Static("", id="glance")
            yield Static("1-4 open a door   k switch track   p switch profile   q quit", id="footer")

    @staticmethod
    def _door_text(key: str, name: str, blurb: str) -> Text:
        t = Text()
        t.append(f"[{key}] ", style=f"bold {theme.GOLD}")
        t.append(f"{name:<10}", style=f"bold {theme.INFO}")
        t.append(blurb, style=theme.TEXT)
        return t

    def on_mount(self) -> None:
        self._refresh()

    def on_screen_resume(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        con = self.app.con
        name = self.app.state.profile_name or ""
        track = self.app.state.track
        self.query_one("#welcome", Static).update(f"Inspector on duty: {name}")

        t = Text("TRACK  ", style=f"bold {theme.MUTED}")
        for tr in tracks.TRACKS:
            if tr == track:
                t.append(f"[ {tracks.NAMES[tr]} ]", style=f"bold reverse {theme.GOLD}")
            else:
                t.append(f"  {tracks.NAMES[tr]}  ", style=theme.MUTED)
            t.append("  ")
        t.append("k switch", style=theme.MUTED)
        self.query_one("#track", Static).update(t)
        for key, door, blurb, screen in DOORS:
            text = QAQC_BLURBS[screen] if track == "qaqc" else blurb
            self.query_one(f"#door-{screen}", Static).update(self._door_text(key, door, text))

        pid = self.app.state.profile_id
        streak = 0
        if pid is not None:
            if track == "osha":
                row = con.execute("SELECT days_without_incident FROM profiles WHERE id=?", (pid,)).fetchone()
                streak = row["days_without_incident"] if row else 0
            else:
                from ...game.rules import track_streak
                streak = track_streak(con, pid, track)["days_without_incident"]
        if track == "osha":
            facts = self._count("SELECT COUNT(*) FROM bank.facts WHERE track='osha'")
            items = self._count("SELECT COUNT(*) FROM bank.checklist_items")
            ticked = self._count(
                "SELECT COUNT(*) FROM checklist_ticks WHERE profile_id=? "
                "AND cid NOT IN (SELECT cid FROM bank.qaqc_checklist_items)", (pid,)) if pid else 0
        else:
            facts = self._count("SELECT COUNT(*) FROM bank.facts WHERE track='qaqc'")
            items = self._count("SELECT COUNT(*) FROM bank.qaqc_checklist_items")
            ticked = self._count(
                "SELECT COUNT(*) FROM checklist_ticks WHERE profile_id=? "
                "AND cid IN (SELECT cid FROM bank.qaqc_checklist_items)", (pid,)) if pid else 0
        questions = self._count("SELECT COUNT(*) FROM bank.questions WHERE track=?", (track,))
        rated = self._count("SELECT COUNT(*) FROM interview_ratings WHERE profile_id=?", (pid,)) if pid else 0
        tail = f"   scenarios rated {rated}" if track == "osha" else ""
        self.query_one("#glance", Static).update(
            f"days without incident {streak}   questions {questions}   facts {facts}   "
            f"checklist items ticked {ticked}/{items}{tail}"
        )

    def _count(self, sql: str, params: tuple = ()) -> int:
        try:
            return int(self.app.con.execute(sql, params).fetchone()[0])
        except Exception:
            return 0

    def action_switch_track(self) -> None:
        new = tracks.other(self.app.state.track)
        if not tracks.has_track(self.app.con, new):
            self.app.notify("The QA/QC track is not built yet -- run ./dashboard.sh qaqc build",
                            severity="warning")
            return
        self.app.state.track = new
        self.app.sub_title = f"{tracks.NAMES[new]} dashboard"
        self.app.notify(f"Track: {tracks.NAMES[new]}")
        self._refresh()

    def action_door(self, screen: str) -> None:
        if screen == "interview" and self.app.state.track != "osha":
            self.app.notify("Interview has OSHA scenarios only -- press k to switch to OSHA 30.",
                            severity="warning")
            return
        self.app.show(screen)

    def action_switch_profile(self) -> None:
        while len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        self.app.state.profile_id = None
        self.app.state.profile_name = None
        self.app.state.active_shift = None
        self.app.state.active_exam = None

    def action_quit_app(self) -> None:
        self.app.action_quit_app()
