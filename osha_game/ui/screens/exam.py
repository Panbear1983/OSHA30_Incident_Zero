"""The timed 30-question mock exam: no per-question feedback, no confidence bet, no near-miss
retry -- answer and move on, score revealed only at the end by ExamResultsScreen. See
game/rules.py's Exam class for the exact scoring mechanics this screen renders.
"""
import json
import random

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from .. import theme
from . import modal
from ...content.segment import TOPICS
from ...game import mastery, rules


class ExamScreen(Screen):
    """Plays one timed mock exam drawn from every currently-unlocked module."""

    DEFAULT_CSS = f"""
    ExamScreen {{
        align: center middle;
    }}
    #card {{
        width: 90;
        height: auto;
        max-height: 90%;
        background: {theme.PANEL};
        border: heavy {theme.MUTED};
        padding: 1 3;
    }}
    #topbar {{
        height: auto;
        margin-bottom: 1;
    }}
    #header {{
        width: 1fr;
        color: {theme.MUTED};
    }}
    #clock {{
        width: auto;
        text-style: bold;
        color: {theme.TEXT};
    }}
    #question {{
        margin-bottom: 1;
        min-height: 3;
    }}
    .opt {{
        margin-bottom: 1;
        color: {theme.TEXT};
    }}
    #footer {{
        margin-top: 1;
        color: {theme.MUTED};
    }}
    """

    BINDINGS = [
        Binding("1", "pick(1)", "Answer 1", show=True),
        Binding("2", "pick(2)", "Answer 2", show=True),
        Binding("3", "pick(3)", "Answer 3", show=True),
        Binding("4", "pick(4)", "Answer 4", show=True),
        Binding("escape", "abort", "Abort exam", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.exam = None
        self.total_seconds = 0
        self.seconds_left = 0
        self.index = 0
        self._current_options: list[str] = []
        self._timer = None
        self._finished = False

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            with Horizontal(id="topbar"):
                yield Static("", id="header")
                yield Static("", id="clock")
            yield Static("", id="question")
            yield Static("", id="opt1", classes="opt")
            yield Static("", id="opt2", classes="opt")
            yield Static("", id="opt3", classes="opt")
            yield Static("", id="opt4", classes="opt")
            yield Static("1-4 answer   esc abort exam", id="footer")

    def on_mount(self) -> None:
        con = self.app.con
        pid = self.app.state.profile_id
        if not mastery.exam_unlocked(con, pid):
            self.app.notify("Exam is still locked.", severity="warning")
            self.app.pop_screen()
            return

        unlocked = mastery.unlocked_modules(con, pid)
        size = self.app.cfg["game"]["exam_questions"]
        self.exam = rules.Exam(con, pid, unlocked, size=size)
        self.app.state.active_exam = self.exam
        self.total_seconds = self.app.cfg["game"]["exam_seconds"]
        self.seconds_left = self.total_seconds
        self.index = 0
        self._current_options = []

        if not self.exam.questions:
            self.app.notify("No exam questions available.", severity="warning")
            self.app.pop_screen()
            return

        self._render_question()
        self._render_clock()
        self._timer = self.set_interval(1.0, self._tick)

    def _render_clock(self) -> None:
        clock = self.query_one("#clock", Static)
        mins, secs = divmod(max(self.seconds_left, 0), 60)
        clock.update(f"{mins:02d}:{secs:02d}")
        clock.styles.color = theme.DANGER if self.seconds_left <= 300 else theme.TEXT

    def _tick(self) -> None:
        self.seconds_left -= 1
        self._render_clock()
        if self.seconds_left <= 0:
            self._timer.stop()
            self._finish()

    def _render_question(self) -> None:
        q = self.exam.questions[self.index]
        self._current_options = json.loads(q["options"])
        random.shuffle(self._current_options)

        self.query_one("#header", Static).update(f"Question {self.index + 1}/{self.exam.total}")

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

    def action_pick(self, n: int) -> None:
        if self.exam is None or self.index >= self.exam.total:
            return
        if n - 1 >= len(self._current_options):
            return
        chosen = self._current_options[n - 1]
        self.exam.answer(self.index, chosen)
        self.index += 1
        if self.index >= self.exam.total:
            self._finish()
        else:
            self._render_question()

    @work
    async def action_abort(self) -> None:
        # push_screen_wait() requires a worker context (Textual 7.5) -- @work supplies one,
        # matching the confirm-then-act pattern documented in screens/modal.py.
        confirmed = await self.app.push_screen_wait(
            modal.ConfirmModal("Abort this exam? It will not be scored or recorded.")
        )
        if confirmed:
            if self._timer is not None:
                self._timer.stop()
            self.app.state.active_exam = None
            self.app.pop_screen()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._timer is not None:
            self._timer.stop()
        elapsed = self.total_seconds - max(self.seconds_left, 0)
        pass_pct = self.app.cfg["game"]["exam_pass_pct"]
        result = self.exam.finish(pass_pct=pass_pct, duration_s=elapsed)
        self.app.state.active_exam = None
        self.app.pop_screen()
        self.app.show("examresults", result=result)


class ExamResultsScreen(Screen):
    """Final exam scorecard: pass/fail banner, per-module breakdown, and full review of every
    missed question. `result` is exactly the dict returned by game.rules.Exam.finish().
    ExamScreen already popped itself before pushing this screen, so leaving here is a plain
    pop back to whatever was underneath (HomeScreen)."""

    DEFAULT_CSS = f"""
    ExamResultsScreen {{
        align: center top;
    }}
    #results-body {{
        width: 100%;
        max-width: 100;
        padding: 1 2;
    }}
    #banner {{
        text-align: center;
        width: 100%;
        height: 3;
        content-align: center middle;
    }}
    #breakdown {{
        background: {theme.PANEL};
        border: heavy {theme.MUTED};
        padding: 1 2;
        margin-bottom: 1;
        width: 100%;
        height: auto;
        color: {theme.TEXT};
    }}
    #missed-heading {{
        text-style: bold;
        color: {theme.TEXT};
        margin-bottom: 1;
    }}
    .missed-panel {{
        border: heavy {theme.DANGER};
        background: {theme.PANEL};
        padding: 1 2;
        margin-bottom: 1;
        width: 100%;
        height: auto;
    }}
    .missed-prompt {{
        color: {theme.TEXT};
        text-style: bold;
        margin-bottom: 1;
    }}
    .missed-chosen {{
        color: {theme.DANGER};
    }}
    .missed-correct {{
        color: {theme.SAFE};
    }}
    .missed-citation {{
        color: {theme.MUTED};
        text-style: italic;
        margin-top: 1;
    }}
    #footer-hint {{
        text-align: center;
        width: 100%;
        color: {theme.MUTED};
        margin-top: 2;
    }}
    """

    def __init__(self, result: dict):
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="results-body"):
            yield Static(self._banner(), id="banner")
            yield Static(self._breakdown_text(), id="breakdown")

            missed = [a for a in self.result.get("answers", []) if not a["correct"]]
            if missed:
                yield Static(f"MISSED ({len(missed)})", id="missed-heading")
                for a in missed:
                    yield self._missed_panel(a)

            yield Static("press any key to continue", id="footer-hint")

    def on_mount(self) -> None:
        scroll = self.query_one("#results-body", VerticalScroll)
        scroll.can_focus = True
        scroll.focus()

    def _banner(self) -> Text:
        passed = self.result.get("passed", False)
        correct = self.result.get("correct", 0)
        total = self.result.get("total", 0)
        pct = self.result.get("pct", 0.0)
        color = theme.SAFE if passed else theme.DANGER
        label = "PASS" if passed else "FAIL"
        t = Text(label, style=f"bold {color}")
        t.append(f"  {correct}/{total} ({pct:.0f}%)")
        return t

    def _breakdown_text(self) -> str:
        lines = []
        for mid in sorted(self.result.get("by_module", {})):
            slot = self.result["by_module"][mid]
            topic = TOPICS.get(mid, f"Module {mid}")
            lines.append(f"M{mid:02d} {topic:<30} {slot['correct']}/{slot['total']}")
        return "\n".join(lines)

    def _missed_panel(self, a: dict) -> Vertical:
        prompt = a.get("prompt", "")
        chosen = a.get("chosen", "")
        correct_answer = a.get("correct_answer", "")
        cfr = a.get("cfr")
        page = a.get("page")

        children = [
            Static(prompt, classes="missed-prompt"),
            Static(f"you answered: {chosen}", classes="missed-chosen"),
            Static(f"correct: {correct_answer}", classes="missed-correct"),
        ]

        citation_parts = []
        if cfr:
            citation_parts.append(str(cfr))
        if page:
            citation_parts.append(f"p. {page}")
        if citation_parts:
            children.append(Static("  ".join(citation_parts), classes="missed-citation"))

        return Vertical(*children, classes="missed-panel")

    def on_key(self, event) -> None:
        self.app.pop_screen()
