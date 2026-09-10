"""Shift-end debrief: outcome banner, score line, streak counter, and a full incident report
for every miss during the shift, plus a terse near-miss log. ShiftScreen pops itself and
pushes this screen directly on top of HomeScreen, so returning from here is a plain pop back
to HomeScreen -- no other stack surgery needed."""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Digits, Static

from .. import theme


class DebriefScreen(Screen):
    """Shift summary screen. `summary` is exactly the dict returned by
    game.rules.Shift.finish() -- see that method's docstring/return for the shape."""

    DEFAULT_CSS = f"""
    DebriefScreen {{
        align: center top;
    }}

    #debrief-body {{
        width: 100%;
        max-width: 100;
        padding: 1 2;
    }}

    #banner {{
        text-style: bold;
        text-align: center;
        width: 100%;
        height: 3;
        content-align: center middle;
    }}

    .banner-clean {{
        color: {theme.SAFE};
    }}

    .banner-incident {{
        color: {theme.DANGER};
    }}

    #stats-line {{
        text-align: center;
        width: 100%;
        color: {theme.TEXT};
        margin-bottom: 1;
    }}

    #streak-block {{
        align: center middle;
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }}

    #streak-digits {{
        width: auto;
        color: {theme.GOLD};
    }}

    #streak-label {{
        text-align: center;
        width: 100%;
        color: {theme.MUTED};
        text-style: bold;
    }}

    #streak-best {{
        text-align: center;
        width: 100%;
        color: {theme.MUTED};
    }}

    .incident-panel {{
        border: heavy {theme.DANGER};
        background: {theme.PANEL};
        padding: 1 2;
        margin-bottom: 1;
        width: 100%;
        height: auto;
    }}

    .incident-prompt {{
        color: {theme.TEXT};
        text-style: bold;
        margin-bottom: 1;
    }}

    .incident-chosen {{
        color: {theme.DANGER};
    }}

    .incident-correct {{
        color: {theme.SAFE};
    }}

    .incident-explanation {{
        color: {theme.TEXT};
        margin-top: 1;
    }}

    .incident-citation {{
        color: {theme.MUTED};
        text-style: italic;
        margin-top: 1;
    }}

    .near-miss-line {{
        color: {theme.WARN};
        width: 100%;
    }}

    #footer-hint {{
        text-align: center;
        width: 100%;
        color: {theme.MUTED};
        margin-top: 2;
    }}
    """

    BINDINGS = [
        Binding("enter", "continue_debrief", "Continue", show=True),
    ]

    def __init__(self, summary: dict):
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        is_clean = self.summary.get("outcome") == "clean"
        banner_text = "CLEAN SHIFT" if is_clean else "INCIDENT"
        banner_class = "banner-clean" if is_clean else "banner-incident"

        with VerticalScroll(id="debrief-body"):
            yield Static(banner_text, id="banner", classes=banner_class)
            yield Static(self._stats_line(), id="stats-line")

            with Vertical(id="streak-block"):
                yield Digits(str(self.summary.get("streak", 0)), id="streak-digits")
                yield Static("DAYS WITHOUT INCIDENT", id="streak-label")
                yield Static(f"(best: {self.summary.get('best_streak', 0)})", id="streak-best")

            for report in self.summary.get("incident_reports", []):
                yield self._incident_panel(report)

            for entry in self.summary.get("near_miss_log", []):
                yield Static(self._near_miss_line(entry), classes="near-miss-line")

            yield Static("press enter to continue", id="footer-hint")

    def on_mount(self) -> None:
        scroll = self.query_one("#debrief-body", VerticalScroll)
        scroll.can_focus = True
        scroll.focus()

    def _stats_line(self) -> str:
        score = self.summary.get("score", 0)
        correct = self.summary.get("correct", 0)
        near_misses = self.summary.get("near_misses", 0)
        incidents = self.summary.get("incidents", 0)
        return (
            f"SCORE {score}   CORRECT {correct}   "
            f"NEAR MISSES {near_misses}   INCIDENTS {incidents}"
        )

    def _incident_panel(self, report: dict) -> Vertical:
        prompt = report.get("prompt", "")
        chosen = report.get("chosen", "")
        correct = report.get("correct", "")
        explanation = report.get("explanation")
        cfr = report.get("cfr")
        page = report.get("page")

        children = [
            Static(prompt, classes="incident-prompt"),
            Static(f"WHAT YOU SAID:  {chosen}", classes="incident-chosen"),
            Static(f"WHAT THE STANDARD SAYS:  {correct}", classes="incident-correct"),
        ]
        if explanation:
            children.append(Static(explanation, classes="incident-explanation"))

        citation_parts = []
        if cfr:
            citation_parts.append(str(cfr))
        if page:
            citation_parts.append(f"Study Guide p. {page}")
        if citation_parts:
            children.append(Static("  ".join(citation_parts), classes="incident-citation"))

        panel = Vertical(*children, classes="incident-panel")
        panel.border_title = "INCIDENT REPORT"
        return panel

    def _near_miss_line(self, entry: dict) -> str:
        prompt = entry.get("prompt", "")
        return f"NEAR MISS -- {prompt[:70]} -- corrected on second look"

    def action_continue_debrief(self) -> None:
        self.app.pop_screen()
