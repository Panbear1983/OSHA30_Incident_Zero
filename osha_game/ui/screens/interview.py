"""Interview: read a scenario, think it through out loud, reveal the guide's own answer, rate
yourself. Self-rated only -- nothing here touches the game's scoring, FSRS scheduling, or
the shift/attempt tables, and nothing is ever written to bank.db.

Two views on one screen:
  picker   -- "ALL MODULES (random)" plus the 23 modules with "rated n/m" for this profile
  scenario -- title, prompt panel, hidden answer; space reveals, 1/2/3 rates, s skips
"""
import json
import random
from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .. import theme
from ...content.segment import TOPICS

_ALL = "all"
_RATING_LABEL = {1: "shaky", 2: "okay", 3: "solid"}
_SECTIONS = (
    ("standards", "STANDARDS"),
    ("numbers", "NUMBERS"),
    ("terms", "KEY TERMS"),
    ("rules", "RULES"),
    ("steps", "SUGGESTED STEPS"),
)


class InterviewScreen(Screen):
    DEFAULT_CSS = f"""
    InterviewScreen {{
        align: center top;
    }}
    InterviewScreen > Vertical {{
        width: 100%;
        max-width: 120;
        height: 100%;
        padding: 1 2;
    }}
    InterviewScreen #title {{
        color: {theme.INFO};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    InterviewScreen #picker {{
        height: 1fr;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
    }}
    InterviewScreen #scenario-title {{
        color: {theme.GOLD};
        text-style: bold;
        height: auto;
        margin-bottom: 1;
    }}
    InterviewScreen #prompt {{
        height: auto;
        border: heavy {theme.INFO};
        background: {theme.PANEL};
        padding: 1 2;
        margin-bottom: 1;
    }}
    InterviewScreen #answer {{
        height: 1fr;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
        padding: 0 1;
    }}
    InterviewScreen .section-header {{
        text-style: bold;
        color: {theme.INFO};
        margin-top: 1;
    }}
    InterviewScreen .entry {{
        color: {theme.TEXT};
        margin-bottom: 1;
    }}
    InterviewScreen #hint {{
        color: {theme.MUTED};
        height: 1;
        text-align: center;
        margin-top: 1;
    }}
    InterviewScreen .hidden {{
        display: none;
    }}
    """

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("space", "reveal", "Reveal answer", show=True),
        Binding("enter", "reveal", "Reveal answer", show=False),
        Binding("1", "rate(1)", "Shaky", show=True),
        Binding("2", "rate(2)", "Okay", show=True),
        Binding("3", "rate(3)", "Solid", show=True),
        Binding("s", "skip", "Skip", show=True),
    ]

    def __init__(self):
        super().__init__()
        self._mode = "picker"          # 'picker' | 'scenario'
        self._scope = None             # _ALL or a module id
        self._current: dict | None = None
        self._revealed = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("INTERVIEW", id="title")
            yield OptionList(id="picker")
            yield Static("", id="scenario-title", classes="hidden")
            yield Static("", id="prompt", classes="hidden")
            yield VerticalScroll(id="answer", classes="hidden")
            yield Static("", id="hint")

    def on_mount(self) -> None:
        self._show_picker()

    # -- picker ------------------------------------------------------------------------------

    def _rated_counts(self) -> dict[int, tuple[int, int]]:
        """module_id -> (lessons rated at least once, lessons with a scenario)."""
        con = self.app.con
        pid = self.app.state.profile_id
        total = {r["module_id"]: r[1] for r in con.execute(
            "SELECT module_id, COUNT(DISTINCT lesson_id) FROM bank.scenarios GROUP BY module_id"
        ).fetchall()}
        rated = {r["module_id"]: r[1] for r in con.execute(
            "SELECT s.module_id, COUNT(DISTINCT s.lesson_id) FROM interview_ratings r "
            "JOIN bank.scenarios s ON s.sid = r.sid WHERE r.profile_id=? GROUP BY s.module_id",
            (pid,),
        ).fetchall()}
        return {m: (rated.get(m, 0), total.get(m, 0)) for m in total}

    def _show_picker(self) -> None:
        self._mode = "picker"
        self._current = None
        self._revealed = False
        picker = self.query_one("#picker", OptionList)
        picker.clear_options()
        counts = self._rated_counts()
        all_rated = sum(r for r, _ in counts.values())
        all_total = sum(t for _, t in counts.values())
        picker.add_option(Option(Text(f"{'ALL MODULES (random)':<44} rated {all_rated}/{all_total}"), id=_ALL))
        for mod_id in sorted(counts):
            rated, total = counts[mod_id]
            label = f"M{mod_id:02d} {TOPICS.get(mod_id, '')}"
            picker.add_option(Option(Text(f"{label:<44} rated {rated}/{total}"), id=str(mod_id)))
        picker.highlighted = 0        # Textual 7.5: stays None after add_option otherwise
        picker.remove_class("hidden")
        for wid in ("#scenario-title", "#prompt", "#answer"):
            self.query_one(wid).add_class("hidden")
        self.query_one("#hint", Static).update("up/down pick a module   enter start   esc back")
        picker.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "picker" or event.option_id is None:
            return
        self._scope = _ALL if event.option_id == _ALL else int(event.option_id)
        self._next_scenario()

    # -- scenario -----------------------------------------------------------------------------

    def _candidates(self) -> list:
        """Scenarios in scope with this profile's rating history. Prefer the Ollama-written
        narrative when a lesson has both origins; the answer is the same either way."""
        con = self.app.con
        pid = self.app.state.profile_id
        where = "" if self._scope == _ALL else "WHERE s.module_id=?"
        params = () if self._scope == _ALL else (self._scope,)
        rows = con.execute(
            f"SELECT s.*, (SELECT MAX(at) FROM interview_ratings r WHERE r.sid=s.sid AND r.profile_id=?) AS last_rated "
            f"FROM bank.scenarios s {where} ORDER BY s.lesson_id, s.origin",
            (pid, *params),
        ).fetchall()
        by_lesson: dict[int, dict] = {}
        for r in rows:
            d = dict(r)
            cur = by_lesson.get(d["lesson_id"])
            if cur is None or (d["origin"] == "ollama" and cur["origin"] != "ollama"):
                by_lesson[d["lesson_id"]] = d
        return list(by_lesson.values())

    def _next_scenario(self) -> None:
        cands = self._candidates()
        if not cands:
            self.app.notify("No scenarios in the bank -- run ./dashboard.sh build", severity="warning")
            return
        unrated = [c for c in cands if c["last_rated"] is None]
        if self._scope == _ALL and unrated:
            chosen = random.choice(unrated)
        elif unrated:
            chosen = sorted(unrated, key=lambda c: c["lesson_id"])[0]
        else:
            chosen = sorted(cands, key=lambda c: (c["last_rated"], c["lesson_id"]))[0]
        self._current = chosen
        self._render_scenario()

    def _render_scenario(self) -> None:
        self._mode = "scenario"
        self._revealed = False
        sc = self._current
        self.query_one("#picker").add_class("hidden")
        title = self.query_one("#scenario-title", Static)
        origin = "  (AI-written scenario, guide-sourced answer)" if sc["origin"] == "ollama" else ""
        title.update(f"{sc['title']}{origin}")
        title.remove_class("hidden")
        prompt = self.query_one("#prompt", Static)
        prompt.update(sc["prompt"])
        prompt.remove_class("hidden")
        answer = self.query_one("#answer", VerticalScroll)
        answer.remove_children()
        answer.add_class("hidden")
        self.query_one("#hint", Static).update(
            "Think it through out loud, then press space to reveal the guide's answer.   s skip   esc back"
        )
        self.set_focus(None)

    def action_reveal(self) -> None:
        if self._mode != "scenario" or self._revealed or self._current is None:
            return
        self._revealed = True
        answer = self.query_one("#answer", VerticalScroll)
        answer.remove_children()
        data = json.loads(self._current["answer_json"])
        for key, header in _SECTIONS:
            entries = data.get(key) or []
            if not entries:
                continue
            answer.mount(Static(header, classes="section-header"))
            for e in entries:
                answer.mount(Static(self._entry_text(key, e), classes="entry"))
        answer.remove_class("hidden")
        answer.can_focus = True
        answer.focus()
        self.query_one("#hint", Static).update(
            "Rate yourself:  1 shaky   2 okay   3 solid      s skip   esc back"
        )

    @staticmethod
    def _entry_text(key: str, e) -> Text:
        t = Text()
        if key == "steps":
            t.append(f"{theme.GLYPH['arrow']} ", style=theme.GOLD)
            t.append(str(e), style=theme.TEXT)
            return t
        if key == "standards":
            t.append(e.get("cite", ""), style=f"bold {theme.GOLD}")
            t.append("  " + e.get("text", ""), style=theme.TEXT)
        elif key == "numbers":
            t.append(e.get("subject", ""), style=f"bold {theme.GOLD}")
            t.append("  " + e.get("text", ""), style=theme.TEXT)
        elif key == "terms":
            t.append(e.get("term", ""), style=f"bold {theme.GOLD}")
            t.append("  " + e.get("definition", ""), style=theme.TEXT)
        else:
            t.append(e.get("text", ""), style=theme.TEXT)
            if e.get("cfr"):
                t.append(f"  (29 CFR {e['cfr']})", style=theme.MUTED)
        if e.get("page"):
            t.append(f"  p. {e['page']}", style=theme.MUTED)
        return t

    def action_rate(self, rating: int) -> None:
        if self._mode != "scenario" or not self._revealed or self._current is None:
            return
        con = self.app.con
        con.execute(
            "INSERT INTO interview_ratings (profile_id, sid, rating, at) VALUES (?,?,?,?)",
            (self.app.state.profile_id, self._current["sid"], rating,
             datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        self.app.notify(f"Rated {_RATING_LABEL[rating]}.")
        self._next_scenario()

    def action_skip(self) -> None:
        if self._mode != "scenario":
            return
        self._next_scenario()

    def action_back(self) -> None:
        if self._mode == "scenario":
            self._show_picker()
        else:
            self.app.pop_screen()
