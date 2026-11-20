"""Stats dashboard: per-module mastery bars, overall accuracy, accuracy by category, recent
shifts, and exam history. Read-only -- queries self.app.con directly, no game.rules
involvement. Pushed from HomeScreen; escape/b pops straight back."""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from .. import theme
from ...game import mastery, tracks


class StatsScreen(Screen):
    DEFAULT_CSS = f"""
    StatsScreen {{
        align: center top;
    }}

    #stats-body {{
        width: 100%;
        max-width: 110;
        padding: 1 2;
    }}

    #stats-title {{
        text-style: bold;
        text-align: center;
        width: 100%;
        height: 3;
        content-align: center middle;
        color: {theme.INFO};
    }}

    .section-header {{
        text-style: bold;
        color: {theme.INFO};
        margin-top: 2;
        margin-bottom: 1;
    }}

    .stat-line {{
        color: {theme.TEXT};
        width: 100%;
    }}

    .stat-line-muted {{
        color: {theme.MUTED};
        width: 100%;
    }}

    #overall-accuracy {{
        color: {theme.TEXT};
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
        Binding("escape", "back", "Back", show=True),
        Binding("b", "back", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="stats-body"):
            yield Static("STATS", id="stats-title")

            yield Static("MODULE MASTERY", classes="section-header")
            yield Vertical(id="mastery-section")

            yield Static("OVERALL ACCURACY", classes="section-header")
            yield Static("", id="overall-accuracy")

            yield Static("ACCURACY BY CATEGORY", classes="section-header")
            yield Vertical(id="category-section")

            yield Static("RECENT SHIFTS", classes="section-header")
            yield Vertical(id="shifts-section")

            yield Static("EXAM HISTORY", classes="section-header")
            yield Vertical(id="exams-section")

            yield Static("INTERVIEW", classes="section-header")
            yield Vertical(id="interview-section")

            yield Static("esc / b back", id="footer-hint")

    def on_mount(self) -> None:
        con = self.app.con
        profile_id = self.app.state.profile_id
        self.track = self.app.state.track
        if self.track != "osha":
            self.query_one("#stats-title", Static).update(f"STATS -- {tracks.NAMES[self.track]}")

        self._populate_mastery(con, profile_id)
        self._populate_overall_accuracy(con, profile_id)
        self._populate_category(con, profile_id)
        self._populate_shifts(con, profile_id)
        self._populate_exams(con, profile_id)
        self._populate_interview(con, profile_id)

        body = self.query_one("#stats-body", VerticalScroll)
        body.can_focus = True
        body.focus()

    # -- section 1: per-module mastery bars -------------------------------------------------

    def _populate_mastery(self, con, profile_id) -> None:
        container = self.query_one("#mastery-section", Vertical)
        m = mastery.all_mastery(con, profile_id, self.track)
        if not m:
            container.mount(Static("No modules in bank yet.", classes="stat-line-muted"))
            return
        for module_id in sorted(m):
            container.mount(Static(self._mastery_row(module_id, m[module_id]), classes="stat-line"))

    def _mastery_row(self, module_id: int, pct: float) -> Text:
        title = tracks.title(module_id)
        id_field = f"{tracks.label(module_id):<3}"
        title_field = title[:38].ljust(38)
        bar_len = max(0, min(10, round(pct / 10)))
        bar = theme.GLYPH["tile_small"] * bar_len
        color = theme.BAND_COLOR[mastery.band_for(pct)]
        t = Text(f"{id_field}  {title_field} ", style=theme.TEXT)
        t.append(bar.ljust(10), style=color)
        t.append(f" {pct:>3.0f}%", style=color)
        return t

    # -- section 2: overall accuracy ---------------------------------------------------------

    def _populate_overall_accuracy(self, con, profile_id) -> None:
        rows = con.execute(
            "SELECT result, COUNT(*) FROM attempts WHERE profile_id=? AND "
            f"{tracks.attempt_qid_clause(self.track)} GROUP BY result",
            (profile_id,),
        ).fetchall()
        counts = {"hit": 0, "near_miss": 0, "incident": 0}
        for row in rows:
            counts[row["result"]] = row[1]
        total = sum(counts.values())
        hit_rate = 100.0 * counts["hit"] / total if total else 0.0
        text = (
            f"HIT {counts['hit']}   NEAR MISS {counts['near_miss']}   "
            f"INCIDENT {counts['incident']}   HIT RATE {hit_rate:.0f}%   "
            f"({total} attempts total)"
        )
        self.query_one("#overall-accuracy", Static).update(text)

    # -- section 3: accuracy by category ------------------------------------------------------

    def _populate_category(self, con, profile_id) -> None:
        container = self.query_one("#category-section", Vertical)
        rows = con.execute(
            "SELECT q.category, a.result, COUNT(*) FROM attempts a "
            "JOIN bank.questions q ON q.qid = a.qid WHERE a.profile_id=? AND q.track=? "
            "GROUP BY q.category, a.result",
            (profile_id, self.track),
        ).fetchall()
        if not rows:
            container.mount(Static("No attempts recorded yet.", classes="stat-line-muted"))
            return

        agg: dict[str, dict[str, int]] = {}
        for row in rows:
            slot = agg.setdefault(row["category"], {"hit": 0, "near_miss": 0, "incident": 0})
            slot[row["result"]] = row[2]

        container.mount(Static(self._category_header(), classes="stat-line"))
        for category in sorted(agg):
            container.mount(Static(self._category_row(category, agg[category]), classes="stat-line"))

    def _category_header(self) -> Text:
        return Text(
            f"{'CATEGORY':<28}{'HIT':>6}{'NEAR MISS':>11}{'INCIDENT':>10}{'HIT%':>7}",
            style=f"bold {theme.MUTED}",
        )

    def _category_row(self, category: str, counts: dict) -> Text:
        hit = counts.get("hit", 0)
        near = counts.get("near_miss", 0)
        inc = counts.get("incident", 0)
        total = hit + near + inc
        pct = 100.0 * hit / total if total else 0.0
        line = f"{category[:28]:<28}{hit:>6}{near:>11}{inc:>10}{pct:>6.0f}%"
        return Text(line, style=theme.TEXT)

    # -- section 4: recent shifts --------------------------------------------------------------

    def _populate_shifts(self, con, profile_id) -> None:
        container = self.query_one("#shifts-section", Vertical)
        rows = con.execute(
            "SELECT started_at, outcome, score, correct, incidents FROM shifts "
            f"WHERE profile_id=? AND {tracks.shift_module_clause(self.track)} "
            "ORDER BY started_at DESC LIMIT 10",
            (profile_id,),
        ).fetchall()
        if not rows:
            container.mount(Static("No shifts logged yet.", classes="stat-line-muted"))
            return
        for row in rows:
            container.mount(Static(self._shift_line(row), classes="stat-line"))

    def _shift_line(self, row) -> str:
        date = (row["started_at"] or "")[:16]
        outcome = (row["outcome"] or "in progress").upper()
        score = row["score"] if row["score"] is not None else 0
        correct = row["correct"] if row["correct"] is not None else 0
        incidents = row["incidents"] if row["incidents"] is not None else 0
        return (
            f"{date:<16}  {outcome:<10}  score {score:<4} "
            f"correct {correct:<3} incidents {incidents}"
        )

    # -- section 5: exam history -----------------------------------------------------------------

    def _populate_exams(self, con, profile_id) -> None:
        container = self.query_one("#exams-section", Vertical)
        if self.track != "osha":
            container.mount(Static("The mock exam is OSHA 30 only; QA/QC has no exam.",
                                   classes="stat-line-muted"))
            return
        rows = con.execute(
            "SELECT at, total, correct, passed FROM exams "
            "WHERE profile_id=? ORDER BY at DESC LIMIT 5",
            (profile_id,),
        ).fetchall()
        if not rows:
            container.mount(Static("No exams taken yet.", classes="stat-line-muted"))
            return
        for row in rows:
            container.mount(Static(self._exam_line(row), classes="stat-line"))

    def _exam_line(self, row) -> str:
        date = (row["at"] or "")[:16]
        total = row["total"] or 0
        correct = row["correct"] or 0
        status = "PASS" if row["passed"] else "FAIL"
        return f"{date:<16}  {correct}/{total}  {status}"

    # -- section 6: interview self-ratings (read-only; written by InterviewScreen) ----------------

    def _populate_interview(self, con, profile_id) -> None:
        container = self.query_one("#interview-section", Vertical)
        if self.track != "osha":
            container.mount(Static("Interview scenarios are OSHA 30 only.", classes="stat-line-muted"))
            return
        row = con.execute(
            "SELECT COUNT(*), AVG(rating) FROM interview_ratings WHERE profile_id=?", (profile_id,)
        ).fetchone()
        count, avg = row[0] or 0, row[1]
        if not count:
            container.mount(Static("No scenarios rated yet.", classes="stat-line-muted"))
            return
        container.mount(Static(
            f"RATED {count}   AVERAGE {avg:.1f}/3", classes="stat-line"))
        rows = con.execute(
            "SELECT r.at, r.rating, s.module_id, s.title FROM interview_ratings r "
            "LEFT JOIN bank.scenarios s ON s.sid = r.sid WHERE r.profile_id=? "
            "ORDER BY r.at DESC LIMIT 5",
            (profile_id,),
        ).fetchall()
        for r in rows:
            date = (r["at"] or "")[:16]
            mod = f"M{r['module_id']:02d}" if r["module_id"] else "M??"
            title = (r["title"] or "")[:40]
            container.mount(Static(f"{date:<16}  {mod}  {title:<40}  {r['rating']}/3", classes="stat-line"))

    # -- navigation -------------------------------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()
