"""The core play loop: presents one question at a time from a game.rules.Shift, handles
answer/retry/bet input, flashes the outcome, and hands off to DebriefScreen when the shift
is done. See game/rules.py's Shift class for the exact scoring/near-miss/incident mechanics
this screen renders.
"""
import json
import random

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from .. import fx, theme
from . import modal
from ...game import rules


class ShiftScreen(Screen):
    """Plays one shift: a fixed-size run of questions against a single module (or, when
    module_id is None, drawn from across the bank per compose.shift_questions' priority)."""

    DEFAULT_CSS = """
    ShiftScreen {
        align: center middle;
    }
    #card {
        width: 90;
        height: auto;
        max-height: 90%;
        background: #161b22;
        border: heavy #30363d;
        padding: 1 3;
    }
    #header {
        color: #6e7681;
        margin-bottom: 1;
    }
    #question {
        margin-bottom: 1;
        min-height: 3;
    }
    .opt {
        margin-bottom: 1;
        color: #c9d1d9;
    }
    #status {
        margin-top: 1;
        min-height: 1;
        color: #58a6ff;
    }
    #footer {
        margin-top: 1;
        color: #6e7681;
    }
    """

    BINDINGS = [
        Binding("1", "pick(1)", "Answer 1", show=True),
        Binding("2", "pick(2)", "Answer 2", show=True),
        Binding("3", "pick(3)", "Answer 3", show=True),
        Binding("4", "pick(4)", "Answer 4", show=True),
        Binding("c", "toggle_bet", "Confidence bet", show=True),
        Binding("escape", "abandon", "Abandon shift", show=True),
    ]

    def __init__(self, module_id: int | None = None):
        super().__init__()
        self.module_id = module_id
        self.shift = None
        self._awaiting_retry = False
        self._bet_armed = False
        self._current_options: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static("", id="header")
            yield Static("", id="question")
            yield Static("", id="opt1", classes="opt")
            yield Static("", id="opt2", classes="opt")
            yield Static("", id="opt3", classes="opt")
            yield Static("", id="opt4", classes="opt")
            yield Static("", id="status")
            yield Static(
                "1-4 answer   c confidence bet (x2, forfeits retry)   esc abandon",
                id="footer",
            )

    def on_mount(self) -> None:
        size = self.app.cfg["game"]["shift_size"]
        self.shift = rules.Shift(self.app.con, self.app.state.profile_id, self.module_id, size=size)
        self.app.state.active_shift = self.shift
        self._awaiting_retry = False
        self._bet_armed = False
        self._current_options = []
        if not self.shift.questions:
            self.app.notify("No questions available for this module yet.", severity="warning")
            self.app.pop_screen()
            return
        self._render_question()

    def _render_question(self) -> None:
        q = self.shift.current
        self._current_options = json.loads(q["options"])
        random.shuffle(self._current_options)

        header = (
            f"Q {self.shift.index + 1}/{len(self.shift.questions)}   "
            f"score {self.shift.score}   module {q['module_id']}"
        )
        self.query_one("#header", Static).update(header)

        question = self.query_one("#question", Static)
        if q["kind"] == "blank":
            before, _, after = q["prompt"].partition("____")
            t = Text(before)
            t.append(" ____ ", style=f"bold {theme.GOLD}")
            t.append(after)
            question.update(t)
        else:
            question.update(q["prompt"])

        for i, opt in enumerate(self._current_options, start=1):
            self.query_one(f"#opt{i}", Static).update(f"{i}. {opt}")

        self.query_one("#status", Static).update("")

    def action_pick(self, n: int) -> None:
        if self.shift is None or self.shift.current is None:
            return
        if n - 1 >= len(self._current_options):
            return
        chosen = self._current_options[n - 1]
        if self._awaiting_retry:
            outcome = self.shift.retry(chosen)
        else:
            outcome = self.shift.answer(chosen, bet=self._bet_armed)
        self._handle_outcome(outcome)

    def action_toggle_bet(self) -> None:
        if self._awaiting_retry:
            return
        self._bet_armed = not self._bet_armed
        card = self.query_one("#card")
        if self._bet_armed:
            card.add_class("bet-armed")
        else:
            card.remove_class("bet-armed")

    async def action_abandon(self) -> None:
        confirmed = await self.app.push_screen_wait(
            modal.ConfirmModal("Abandon this shift? Answered questions are still recorded.")
        )
        if confirmed:
            self.shift.abandon()
            self.app.state.active_shift = None
            self.app.pop_screen()

    def _handle_outcome(self, outcome) -> None:
        status = self.query_one("#status", Static)
        if outcome.result == "near_miss_pending":
            self._awaiting_retry = True
            status.update("NEAR MISS -- look again.")
            return

        card = self.query_one("#card")
        if outcome.correct:
            fx.flash(card, "hit-flash")
            status.update(f"CLEAR  +{outcome.score_delta}")
        else:
            fx.flash(card, "miss-flash")
            inc = outcome.incident
            detail = inc["explanation"] or ""
            if inc["cfr"]:
                detail += f"  ({inc['cfr']})"
            if inc["page"]:
                detail += f"  -- p. {inc['page']}"
            status.update(f"VIOLATION -- {detail}")

        self._awaiting_retry = False
        self._bet_armed = False
        card.remove_class("bet-armed")
        self.set_timer(1.2, self._advance)

    def _advance(self) -> None:
        if self.shift.done:
            summary = self.shift.finish()
            self.app.state.active_shift = None
            self.app.pop_screen()
            self.app.show("debrief", summary=summary)
        else:
            self._render_question()
