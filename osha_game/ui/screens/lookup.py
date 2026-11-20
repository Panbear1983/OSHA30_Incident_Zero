"""Look Up: type words, get facts. No scoring, no scheduling, nothing written to progress.db.
Can be opened with a prefilled query (Inspect does this for a checklist item)."""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .. import theme
from ...lookup import search as srch

_FILTERS = (None,) + srch.KINDS
_TRACK_FILTERS = ("osha", "qaqc", None)        # ctrl+t cycles; None = both tracks


class LookupScreen(Screen):
    DEFAULT_CSS = f"""
    LookupScreen {{
        align: center top;
    }}
    LookupScreen > Vertical {{
        width: 100%;
        max-width: 120;
        height: 100%;
        padding: 1 2;
    }}
    LookupScreen #title {{
        color: {theme.INFO};
        text-style: bold;
        text-align: center;
        height: 1;
    }}
    LookupScreen #query {{
        margin-top: 1;
        border: heavy {theme.GOLD};
        background: {theme.PANEL};
    }}
    LookupScreen #filter-line {{
        color: {theme.MUTED};
        height: 1;
        margin-bottom: 1;
    }}
    LookupScreen #results {{
        height: 1fr;
        min-height: 6;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
    }}
    LookupScreen #detail {{
        height: auto;
        min-height: 5;
        max-height: 12;
        border: round {theme.INFO};
        background: {theme.PANEL};
        padding: 0 1;
        margin-top: 1;
    }}
    LookupScreen #hint {{
        color: {theme.MUTED};
        height: 1;
        text-align: center;
        margin-top: 1;
    }}
    """

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("ctrl+f", "cycle_filter", "Filter kind", show=True),
        Binding("ctrl+t", "cycle_track", "Track", show=True),
        Binding("ctrl+l", "focus_query", "Edit query", show=True),
    ]

    def __init__(self, query: str = "", kind: str | None = None, track: str | None = ""):
        super().__init__()
        self._initial_query = query
        self._filter_ix = _FILTERS.index(kind) if kind in _FILTERS else 0
        self._initial_track = track            # "" = follow the dashboard's track
        self._track_ix = 0
        self._hits: list[dict] = []
        self._widened = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("LOOK UP", id="title")
            yield Input(placeholder='e.g. "guardrail height", "permanent link", "上鎖掛籤", "1910.95"', id="query")
            yield Static("", id="filter-line")
            yield OptionList(id="results")
            yield Static("Type a question and press enter.", id="detail")
            yield Static("enter search   up/down pick   ctrl+f kind   ctrl+t track   ctrl+l edit query   esc back", id="hint")

    def on_mount(self) -> None:
        track = self.app.state.track if self._initial_track == "" else self._initial_track
        self._track_ix = _TRACK_FILTERS.index(track) if track in _TRACK_FILTERS else 0
        self._render_filter()
        box = self.query_one("#query", Input)
        if self._initial_query:
            box.value = self._initial_query
            self._run_search()
            self.query_one("#results", OptionList).focus()
        else:
            box.focus()

    # -- search ----------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query":
            self._run_search()
            if self._hits:
                self.query_one("#results", OptionList).focus()

    def _run_search(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        results = self.query_one("#results", OptionList)
        detail = self.query_one("#detail", Static)
        results.clear_options()
        self._hits = []
        if not query:
            detail.update("Type a question and press enter.")
            return
        if not srch.has_facts(self.app.con, schema="bank."):
            detail.update("This bank predates the fact base -- run ./dashboard.sh build")
            return
        kind = _FILTERS[self._filter_ix]
        track = _TRACK_FILTERS[self._track_ix]
        self._hits = srch.search(self.app.con, query, kind=kind, limit=25, schema="bank.", track=track)
        self._widened = False
        if not self._hits and track is not None:
            # Nothing on this track: look on both before giving up, and say so.
            self._hits = srch.search(self.app.con, query, kind=kind, limit=25, schema="bank.", track=None)
            self._widened = bool(self._hits)
        self._render_filter()
        if not self._hits:
            detail.update(f"No facts match {query!r}. Try fewer or different words.")
            return
        for i, d in enumerate(self._hits):
            results.add_option(Option(self._row_text(d), id=str(i)))
        results.highlighted = 0        # Textual 7.5: stays None after add_option otherwise
        self._show_detail(0)

    def _row_text(self, d: dict) -> Text:
        label = srch.KIND_LABEL.get(d["kind"], d["kind"].upper())
        if srch.is_qaqc(d):
            label = "QC " + label
        head = d["subject"] if d["kind"] != "rule" else d["topic"]
        if d.get("zh"):
            head = f"{head} {d['zh']}"
        body = d["value"]
        t = Text()
        t.append(f"{label:<12}", style=f"bold {theme.GOLD}")
        t.append(f"{head[:34]:<35}", style=f"bold {theme.TEXT}")
        room = max(10, 110 - 12 - 35 - 8)
        t.append(body[:room] + ("..." if len(body) > room else ""), style=theme.TEXT)
        if not srch.is_qaqc(d):
            t.append(f"  p.{d['page']}", style=theme.MUTED)
        return t

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "results" and event.option_id is not None:
            self._show_detail(int(event.option_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "results" and event.option_id is not None:
            self._show_detail(int(event.option_id))

    def _show_detail(self, ix: int) -> None:
        if not (0 <= ix < len(self._hits)):
            return
        d = self._hits[ix]
        label = srch.KIND_LABEL.get(d["kind"], d["kind"].upper())
        t = Text()
        t.append(f"{'QA/QC ' if srch.is_qaqc(d) else ''}{label}  ", style=f"bold {theme.GOLD}")
        t.append(d["subject"], style=f"bold {theme.INFO}")
        if d.get("zh"):
            t.append(f"  {d['zh']}", style=f"bold {theme.GOLD}")
        t.append("\n")
        t.append(d["value"], style=theme.TEXT)
        if srch.is_qaqc(d):
            meta = f"Source: {d.get('source_label') or ''}"
            if d["module_id"]:
                meta += f"   Q{d['module_id'] - 100} {d['topic']}"
            if d.get("source_url"):
                meta += f"\n{d['source_url']}"
            t.append("\n" + meta, style=theme.MUTED)
            self.query_one("#detail", Static).update(t)
            return
        meta = f"p.{d['page']}"
        if d["cfr"]:
            meta += f"   29 CFR {d['cfr']}"
        if d["module_id"]:
            meta += f"   M{d['module_id']:02d} {d['topic']}"
        if d["source_doc"] == "sds":
            meta += "   (Sample SDS handout)"
        t.append("\n" + meta, style=theme.MUTED)
        self.query_one("#detail", Static).update(t)

    # -- filter ----------------------------------------------------------------

    def _render_filter(self) -> None:
        kind = _FILTERS[self._filter_ix]
        label = "all kinds" if kind is None else srch.KIND_LABEL[kind]
        track = srch.TRACK_LABEL[_TRACK_FILTERS[self._track_ix]]
        note = "   (nothing there -- showing all tracks)" if self._widened else ""
        self.query_one("#filter-line", Static).update(
            f"showing: {label} in {track}{note}    (ctrl+f kind, ctrl+t track)")

    def action_cycle_filter(self) -> None:
        self._filter_ix = (self._filter_ix + 1) % len(_FILTERS)
        self._render_filter()
        if self.query_one("#query", Input).value.strip():
            self._run_search()

    def action_cycle_track(self) -> None:
        self._track_ix = (self._track_ix + 1) % len(_TRACK_FILTERS)
        self._widened = False
        self._render_filter()
        if self.query_one("#query", Input).value.strip():
            self._run_search()

    def action_focus_query(self) -> None:
        self.query_one("#query", Input).focus()

    def action_back(self) -> None:
        self.app.pop_screen()
