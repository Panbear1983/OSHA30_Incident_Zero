"""Inspect: pick a module, walk its checklist top to bottom, tick items, jump to Look Up for
the detail behind any item, export the list as Word / PDF. Answers one question only --
"did I check everything for module N?" -- so there is no scoring and nothing here feeds the
game's schedule. Items come from bank.checklist_items (read-only); ticks are the only thing
written, and they go to progress.db's checklist_ticks for the current profile.

Two stages inside one screen: the module picker and the walk. escape steps back one stage.
"""
import re
from datetime import datetime, timezone

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .. import theme
from .modal import ConfirmModal
from ...content.segment import TOPICS

_STOP = {
    "a", "an", "the", "of", "to", "in", "on", "for", "is", "are", "be", "and", "or", "must",
    "shall", "with", "by", "at", "from", "it", "its", "this", "that", "these", "those", "any",
    "all", "each", "when", "which", "who", "will", "not", "no", "than", "then", "there", "their",
    "they", "them", "may", "can", "should", "would", "been", "being", "was", "were", "has",
    "have", "had", "into", "onto", "over", "under", "such", "other", "also", "used", "use",
    "employer", "employers", "employee", "employees", "requirements", "required", "following",
}
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def lookup_query_for(text: str, n: int = 4) -> str:
    """The 3-4 longest non-stopword words of an item, in their original order -- what Look Up
    gets handed when the reader wants the facts behind a checklist line."""
    words = [w for w in _WORD.findall(text) if w.lower() not in _STOP]
    seen: set[str] = set()
    uniq = []
    for w in words:
        k = w.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    longest = sorted(uniq, key=lambda w: (-len(w), uniq.index(w)))[:n]
    keep = {w.lower() for w in longest}
    return " ".join(w for w in uniq if w.lower() in keep)


class InspectScreen(Screen):
    DEFAULT_CSS = f"""
    InspectScreen {{
        align: center top;
    }}
    InspectScreen > Vertical {{
        width: 100%;
        max-width: 120;
        height: 100%;
        padding: 1 2;
    }}
    InspectScreen #title {{
        color: {theme.INFO};
        text-style: bold;
        text-align: center;
        height: 1;
    }}
    InspectScreen #subtitle {{
        color: {theme.MUTED};
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    InspectScreen #modules {{
        height: 1fr;
        min-height: 8;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
    }}
    InspectScreen #items {{
        height: 1fr;
        min-height: 6;
        border: round {theme.PANEL_ALT};
        background: {theme.PANEL};
    }}
    InspectScreen #detail {{
        height: auto;
        min-height: 4;
        max-height: 10;
        border: round {theme.INFO};
        background: {theme.PANEL};
        padding: 0 1;
        margin-top: 1;
    }}
    InspectScreen #hint {{
        color: {theme.MUTED};
        height: 1;
        text-align: center;
        margin-top: 1;
    }}
    InspectScreen .hidden {{
        display: none;
    }}
    """

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("space", "toggle", "Tick", show=True),
        Binding("l", "lookup", "Look Up", show=True),
        Binding("x", "export", "Export", show=True),
        Binding("r", "reset_module", "Reset ticks", show=True),
    ]

    _PICK_HINT = "enter walk   x export Word/PDF   esc back"
    _WALK_HINT = "space/enter tick   l look up   r reset ticks   x export   esc modules"

    def __init__(self) -> None:
        super().__init__()
        self.stage = "pick"
        self.module_id: int | None = None
        self._items: list = []               # rows of bank.checklist_items for the open module
        self._ticked: set[str] = set()       # cids ticked for this profile in the open module

    # -- layout ----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("INSPECT", id="title")
            yield Static("Pick a module to walk its checklist.", id="subtitle")
            yield OptionList(id="modules")
            yield OptionList(id="items", classes="hidden")
            yield Static("", id="detail", classes="hidden")
            yield Static(self._PICK_HINT, id="hint")

    def on_mount(self) -> None:
        self._show_picker()

    # -- helpers ---------------------------------------------------------------

    @property
    def _profile_id(self):
        return self.app.state.profile_id

    def _tick_counts(self) -> dict[int, tuple[int, int]]:
        """module_id -> (ticked, total) for the current profile."""
        con = self.app.con
        totals = {r[0]: r[1] for r in con.execute(
            "SELECT module_id, COUNT(*) FROM bank.checklist_items GROUP BY module_id"
        ).fetchall()}
        ticked: dict[int, int] = {}
        if self._profile_id is not None:
            for r in con.execute(
                "SELECT c.module_id, COUNT(*) FROM checklist_ticks t "
                "JOIN bank.checklist_items c ON c.cid = t.cid "
                "WHERE t.profile_id=? GROUP BY c.module_id",
                (self._profile_id,),
            ).fetchall():
                ticked[r[0]] = r[1]
        return {m: (ticked.get(m, 0), n) for m, n in totals.items()}

    def _module_line(self, module_id: int, done: int, total: int) -> Text:
        topic = TOPICS.get(module_id, f"Module {module_id}")
        t = Text()
        t.append(f"M{module_id:02d}  ", style=f"bold {theme.GOLD}")
        t.append(f"{topic:<34}", style=theme.TEXT)
        color = theme.SAFE if total and done == total else (theme.INFO if done else theme.MUTED)
        t.append(f"{done:>4}/{total:<4} ticked", style=color)
        return t

    # -- stage 1: picker -------------------------------------------------------

    def _show_picker(self, keep: int | None = None) -> None:
        self.stage = "pick"
        self.module_id = None
        self._items = []
        self._ticked = set()

        counts = self._tick_counts()
        modules = self.query_one("#modules", OptionList)
        modules.clear_options()
        ids = [r[0] for r in self.app.con.execute("SELECT id FROM bank.modules ORDER BY id").fetchall()]
        for mid in ids:
            done, total = counts.get(mid, (0, 0))
            modules.add_option(Option(self._module_line(mid, done, total), id=str(mid)))
        if modules.option_count:
            modules.highlighted = keep if (keep is not None and keep < modules.option_count) else 0

        self.query_one("#items", OptionList).add_class("hidden")
        self.query_one("#detail", Static).add_class("hidden")
        modules.remove_class("hidden")
        self.query_one("#subtitle", Static).update("Pick a module to walk its checklist.")
        self.query_one("#hint", Static).update(self._PICK_HINT)
        modules.focus()

    # -- stage 2: walk ---------------------------------------------------------

    def _open_walk(self, module_id: int) -> None:
        con = self.app.con
        self._items = con.execute(
            "SELECT c.cid, c.seq, c.text, c.page, c.cfr, c.lesson_id, l.label AS lesson "
            "FROM bank.checklist_items c LEFT JOIN bank.lessons l ON l.id = c.lesson_id "
            "WHERE c.module_id=? ORDER BY c.seq",
            (module_id,),
        ).fetchall()
        if not self._items:
            self.app.notify("No checklist items for that module.", severity="warning")
            return
        self.stage = "walk"
        self.module_id = module_id
        self._ticked = set()
        if self._profile_id is not None:
            self._ticked = {r[0] for r in con.execute(
                "SELECT t.cid FROM checklist_ticks t JOIN bank.checklist_items c ON c.cid = t.cid "
                "WHERE t.profile_id=? AND c.module_id=?",
                (self._profile_id, module_id),
            ).fetchall()}

        items = self.query_one("#items", OptionList)
        items.clear_options()
        for it in self._items:
            items.add_option(Option(self._item_line(it), id=it["cid"]))
        items.highlighted = 0

        self.query_one("#modules", OptionList).add_class("hidden")
        items.remove_class("hidden")
        self.query_one("#detail", Static).remove_class("hidden")
        self._render_walk_header()
        self.query_one("#hint", Static).update(self._WALK_HINT)
        self._show_detail(0)
        items.focus()

    def _render_walk_header(self) -> None:
        topic = TOPICS.get(self.module_id, f"Module {self.module_id}")
        self.query_one("#subtitle", Static).update(
            f"M{self.module_id:02d} {topic}   {len(self._ticked)}/{len(self._items)} ticked"
        )

    def _item_line(self, it) -> Text:
        ticked = it["cid"] in self._ticked
        t = Text()
        t.append("[x] " if ticked else "[ ] ", style=(theme.SAFE if ticked else theme.MUTED))
        room = 110 - 4 - 8
        text = it["text"]
        t.append(text[:room] + ("..." if len(text) > room else ""),
                 style=(theme.MUTED if ticked else theme.TEXT))
        t.append(f"  p.{it['page']}", style=theme.MUTED)
        return t

    def _show_detail(self, ix: int) -> None:
        if not (0 <= ix < len(self._items)):
            return
        it = self._items[ix]
        t = Text()
        t.append(f"{it['seq']}/{len(self._items)}  ", style=f"bold {theme.GOLD}")
        t.append(it["lesson"] or "General", style=f"bold {theme.INFO}")
        t.append("\n")
        t.append(it["text"], style=theme.TEXT)
        meta = f"p.{it['page']}"
        if it["cfr"]:
            meta += f"   29 CFR {it['cfr']}"
        meta += "   ticked" if it["cid"] in self._ticked else "   not ticked"
        t.append("\n" + meta, style=theme.MUTED)
        self.query_one("#detail", Static).update(t)

    def _toggle_current(self) -> None:
        items = self.query_one("#items", OptionList)
        ix = items.highlighted
        if ix is None or not (0 <= ix < len(self._items)) or self._profile_id is None:
            return
        it = self._items[ix]
        con = self.app.con
        if it["cid"] in self._ticked:
            con.execute("DELETE FROM checklist_ticks WHERE profile_id=? AND cid=?",
                        (self._profile_id, it["cid"]))
            self._ticked.discard(it["cid"])
        else:
            con.execute(
                "INSERT OR REPLACE INTO checklist_ticks (profile_id, cid, ticked_at) VALUES (?,?,?)",
                (self._profile_id, it["cid"], datetime.now(timezone.utc).isoformat()),
            )
            self._ticked.add(it["cid"])
        con.commit()
        items.replace_option_prompt_at_index(ix, self._item_line(it))
        items.highlighted = ix
        self._render_walk_header()
        self._show_detail(ix)

    # -- events ----------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "modules" and event.option_id is not None:
            self._open_walk(int(event.option_id))
        elif event.option_list.id == "items":
            self._toggle_current()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "items" and self.stage == "walk" and event.option_index is not None:
            self._show_detail(event.option_index)

    # -- actions ---------------------------------------------------------------

    def action_toggle(self) -> None:
        if self.stage == "walk":
            self._toggle_current()

    def action_lookup(self) -> None:
        if self.stage != "walk":
            return
        ix = self.query_one("#items", OptionList).highlighted
        if ix is None or not (0 <= ix < len(self._items)):
            return
        query = lookup_query_for(self._items[ix]["text"])
        if query:
            self.app.show("lookup", query=query)

    def _picked_module_id(self) -> int | None:
        if self.stage == "walk":
            return self.module_id
        modules = self.query_one("#modules", OptionList)
        ix = modules.highlighted
        if ix is None:
            return None
        opt = modules.get_option_at_index(ix)
        return int(opt.id) if opt.id is not None else None

    def action_export(self) -> None:
        mid = self._picked_module_id()
        if mid is None:
            return
        self.app.notify(f"Exporting module {mid} checklist...")
        self._export_worker(mid)

    @work(thread=True)
    def _export_worker(self, module_id: int) -> None:
        from ... import db, paths
        from ...export import checklist as export_checklist
        out_dir = paths.ROOT / "exports"
        con = db.bank_connect(paths.BANK_DB)     # own connection: sqlite objects are per-thread
        try:
            written = export_checklist.export_module(con, module_id, out_dir, pdf=True)
        except Exception as exc:  # surface, never crash the UI thread
            self.app.call_from_thread(self.app.notify, f"Export failed: {exc}", severity="error")
            return
        finally:
            con.close()
        names = "\n".join(str(p) for p in written)
        self.app.call_from_thread(self.app.notify, f"Wrote:\n{names}", timeout=8)

    @work
    async def action_reset_module(self) -> None:
        if self.stage != "walk" or self._profile_id is None or self.module_id is None:
            return
        topic = TOPICS.get(self.module_id, f"Module {self.module_id}")
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Clear every tick for M{self.module_id:02d} {topic}?")
        )
        if not confirmed:
            return
        con = self.app.con
        con.execute(
            "DELETE FROM checklist_ticks WHERE profile_id=? AND cid IN "
            "(SELECT cid FROM bank.checklist_items WHERE module_id=?)",
            (self._profile_id, self.module_id),
        )
        con.commit()
        keep = self.query_one("#items", OptionList).highlighted or 0
        self._open_walk(self.module_id)
        self.query_one("#items", OptionList).highlighted = keep
        self._show_detail(keep)

    def action_back(self) -> None:
        if self.stage == "walk":
            keep = self.module_id - 1 if self.module_id else 0
            self._show_picker(keep=keep)
        else:
            self.app.pop_screen()
