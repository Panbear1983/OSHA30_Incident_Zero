"""Phase 3 checks: every module has an ordered checklist grounded on its cited pages,
the Word (+ PDF) export works, and the Inspect screen ticks and unticks for real."""
import json

import pytest
import pathlib

from textual.widgets import OptionList

from conftest import run, text_of
from osha_game import paths
from osha_game.content.norm import loose
from osha_game.export import checklist as export_checklist


def test_every_module_has_a_contiguous_checklist(bank_con):
    module_ids = [r[0] for r in bank_con.execute("SELECT id FROM modules ORDER BY id")]
    assert len(module_ids) == 23
    for mid in module_ids:
        seqs = [r[0] for r in bank_con.execute(
            "SELECT seq FROM checklist_items WHERE module_id=? ORDER BY seq", (mid,))]
        assert seqs, f"module {mid} has no checklist items"
        assert seqs == list(range(1, len(seqs) + 1)), f"module {mid} seq not contiguous"


def test_every_item_is_on_its_cited_page(bank_con):
    if not paths.PAGES_GUIDE.exists():
        pytest.skip("page cache absent (needs the source PDF + ./dashboard.sh build)")
    pages = {}
    with open(paths.PAGES_GUIDE) as fh:
        for line in fh:
            r = json.loads(line)
            pages[r["page"]] = loose(r["text"])
    rows = bank_con.execute("SELECT text, page FROM checklist_items").fetchall()
    assert rows
    for text, page in rows:
        assert loose(text)[:400] in pages[page], f"p.{page}: {text[:60]!r} not on page"


def test_export_module_1(bank_con, tmp_path):
    written = export_checklist.export_module(bank_con, 1, tmp_path, pdf=True)
    docx_files = [p for p in written if p.suffix == ".docx"]
    assert len(docx_files) == 1
    from docx import Document
    doc = Document(str(docx_files[0]))
    body = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert "Module 1: Introduction to OSHA" in body
    assert "p. " in cells
    assert "[ ]" in cells
    if export_checklist.soffice_path():
        pdfs = [p for p in written if p.suffix == ".pdf"]
        assert len(pdfs) == 1 and pdfs[0].stat().st_size > 1024
    for p in written:
        assert pathlib.Path(p).parent == tmp_path


def test_inspect_screen_ticks(tmp_progress):
    from osha_game.ui.app import InspectorApp
    from osha_game.ui.screens.dashboard import DashboardScreen
    from osha_game.ui.screens.inspect import InspectScreen

    async def body():
        app = InspectorApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("n")
            await pilot.pause()
            for ch in "pilot":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")          # clock in
            await pilot.pause()
            await pilot.press("space")          # skip splash
            await pilot.pause(0.2)
            assert isinstance(app.screen, DashboardScreen)

            await pilot.press("3")
            await pilot.pause()
            assert isinstance(app.screen, InspectScreen)
            modules = app.screen.query_one("#modules", OptionList)
            assert modules.option_count == 23 and modules.highlighted == 0

            await pilot.press("enter")          # open module 1
            await pilot.pause()
            assert app.screen.stage == "walk" and app.screen.module_id == 1
            items = app.screen.query_one("#items", OptionList)
            assert items.option_count > 0 and items.highlighted == 0

            def ticks():
                return app.con.execute("SELECT COUNT(*) FROM checklist_ticks").fetchone()[0]

            await pilot.press("space")
            await pilot.pause()
            assert ticks() == 1
            assert "1/" in text_of(app.screen.query_one("#subtitle"))
            await pilot.press("space")
            await pilot.pause()
            assert ticks() == 0

            await pilot.press("escape")         # back to picker
            await pilot.pause()
            assert app.screen.stage == "pick"
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

            # bank.db untouched by any of this
            n = app.con.execute("SELECT COUNT(*) FROM bank.checklist_items").fetchone()[0]
            assert n > 0
            await pilot.press("q")

    run(body())
