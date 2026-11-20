"""The separate QA/QC track: bank contents, isolation from the OSHA course (exam, mastery,
streak, stats), grounding, Look Up, Inspect export, migration, and a headless playthrough
of the dashboard track picker -> QA/QC shift."""
import json
import sqlite3

import pytest
from textual.widgets import Input, OptionList, Static

from conftest import run, text_of
from osha_game import paths
from osha_game.content import qaqc, qaqc_sources
from osha_game.export import checklist as export_checklist
from osha_game.lookup import search as srch

QAQC_IDS = [101, 102, 103, 104, 105, 106]


@pytest.fixture
def game_con(tmp_progress):
    from osha_game import db
    con = db.game_connect()
    con.execute("INSERT INTO profiles (name, created_at) VALUES ('t', '2026-01-01')")
    con.commit()
    pid = con.execute("SELECT id FROM profiles").fetchone()[0]
    yield con, pid
    con.close()


# -- bank contents ------------------------------------------------------------------------

def test_osha_bank_untouched_by_track(bank_con):
    """The 925 OSHA questions keep their numbering, pages and origin mix."""
    n = bank_con.execute("SELECT COUNT(*) FROM questions WHERE track='osha'").fetchone()[0]
    assert n == 925
    bad = bank_con.execute(
        "SELECT COUNT(*) FROM questions WHERE track='osha' AND "
        "(source_doc NOT IN ('guide','sds') OR source_url IS NOT NULL OR module_id > 23)").fetchone()[0]
    assert bad == 0
    mods = [r[0] for r in bank_con.execute("SELECT id FROM modules ORDER BY id")]
    assert mods == list(range(1, 24))


def test_every_qaqc_question_has_source(bank_con):
    rows = bank_con.execute(
        "SELECT qid, source_url, source_label, source_doc, page, cfr FROM questions WHERE track='qaqc'"
    ).fetchall()
    assert len(rows) >= 120
    for qid, url, label, doc, page, cfr in rows:
        assert url and url.startswith("https://"), qid
        assert label and label.strip(), qid
        assert doc == "qaqc" and page is None and cfr is None, qid


def test_six_modules_and_seed_quiz(bank_con):
    mods = bank_con.execute("SELECT id, week, title FROM qaqc_modules ORDER BY id").fetchall()
    assert [m[0] for m in mods] == QAQC_IDS
    assert [m[1] for m in mods] == [1, 2, 3, 4, 5, 6]
    per = dict(bank_con.execute(
        "SELECT module_id, COUNT(*) FROM questions WHERE track='qaqc' GROUP BY module_id").fetchall())
    assert sorted(per) == QAQC_IDS
    assert all(n >= 15 for n in per.values()), per
    seeds = bank_con.execute(
        "SELECT COUNT(*) FROM questions WHERE track='qaqc' AND category='qaqc_seed'").fetchone()[0]
    assert seeds >= 29


def test_track_ranges_enforced_by_schema(bank_con):
    """A QA/QC question without a source URL, or one numbered like an OSHA module, is refused
    by the table itself (checked inside a rolled-back savepoint)."""
    bank_con.execute("SAVEPOINT t")
    try:
        for module_id, url in ((101, ""), (7, "https://example.org")):
            with pytest.raises(sqlite3.IntegrityError):
                bank_con.execute(
                    "INSERT INTO questions (qid, kind, category, module_id, prompt, correct, options, "
                    "source_doc, origin, track, source_url, source_label) "
                    "VALUES ('x_test', 'mc', 'qaqc', ?, 'p', 'c', '[]', 'qaqc', 'claude', 'qaqc', ?, 'L')",
                    (module_id, url))
    finally:
        bank_con.execute("ROLLBACK TO t")
        bank_con.execute("RELEASE t")


# -- grounding ----------------------------------------------------------------------------

@pytest.mark.skipif(not qaqc_sources.have_cache(), reason="no QA/QC source cache (./dashboard.sh qaqc fetch)")
def test_generated_questions_are_grounded(bank_con):
    texts = qaqc_sources.loose_texts()
    by_url = {s.url: s.key for s in qaqc_sources.SOURCES}
    rows = bank_con.execute(
        "SELECT qid, correct, source_quote, source_url FROM questions "
        "WHERE track='qaqc' AND category='qaqc'").fetchall()
    assert rows
    for qid, correct, quote, url in rows:
        assert quote, qid
        assert qaqc_sources.grounded(quote, by_url[url], texts), qid
        assert qaqc.answer_anchored(correct, quote), qid


def test_ungrounded_generated_question_is_rejected(monkeypatch):
    texts = {"fluke_pl_channel": qaqc_sources.loose(
        "The maximum permitted length of the permanent link is 90 meters.")}
    base = {"module": 2, "kind": "mc", "explanation": "x", "source": "fluke_pl_channel"}
    entries = [
        dict(base, origin="generated", _file="a#0", prompt="Max permanent link length?",
             correct="90 m", options=["90 m", "100 m", "80 m", "50 m"],
             quote="The maximum permitted length of the permanent link is 90 meters."),
        dict(base, origin="generated", _file="a#1", prompt="Max permanent link length (bad)?",
             correct="80 m", options=["90 m", "100 m", "80 m", "50 m"],
             quote="The maximum permitted length of the permanent link is 80 meters."),
        dict(base, origin="generated", _file="a#2", prompt="Quote on page but answer unsupported?",
             correct="Cat8 only", options=["Cat8 only", "Cat5e", "Cat6", "Cat6A"],
             quote="The maximum permitted length of the permanent link is 90 meters."),
    ]
    monkeypatch.setattr(qaqc, "load_questions", lambda: entries)
    accepted, rep = qaqc.build_questions(texts)
    assert [e["_file"] for _, e in accepted] == ["a#0"]
    reasons = {r["where"]: r["reason"] for r in rep["rejected"]}
    assert reasons == {"a#1": "not_grounded_on_source", "a#2": "answer_not_supported_by_quote"}


# -- Look Up ------------------------------------------------------------------------------

def test_lookup_permanent_link(bank_con):
    hits = srch.search(bank_con, "permanent link", track="qaqc", limit=5)
    assert hits and "permanent link" in hits[0]["subject"].lower()
    assert hits[0]["source_url"].startswith("https://")
    both = srch.search(bank_con, "permanent link", track=None, limit=5)
    assert any(h["track"] == "qaqc" for h in both)


def test_lookup_chinese(bank_con):
    hits = srch.search(bank_con, "上鎖掛籤", track=None, limit=5)
    assert hits and hits[0]["zh"] == "上鎖掛籤"
    assert "lockout" in hits[0]["subject"].lower()


def test_lookup_defaults_to_osha(bank_con):
    """Callers that predate the track keep getting OSHA facts only."""
    for q in ("guardrail height", "permanent link", "fiber"):
        assert all(h["track"] == "osha" for h in srch.search(bank_con, q, limit=25))


def test_glossary_and_numbers(bank_con):
    terms = bank_con.execute("SELECT COUNT(*) FROM facts WHERE track='qaqc' AND kind='term'").fetchone()[0]
    nums = bank_con.execute("SELECT subject FROM facts WHERE track='qaqc' AND kind='threshold'").fetchall()
    assert terms >= 40
    subjects = " | ".join(r[0] for r in nums)
    for needle in ("90 m", "100 m", "0.75 dB", "0.3 dB", "25 lbf", "1.2 cal/cm", "0.008"):
        assert needle in subjects, needle
    missing = bank_con.execute(
        "SELECT COUNT(*) FROM facts WHERE track='qaqc' AND (coalesce(source_url,'')='' "
        "OR coalesce(source_label,'')='')").fetchone()[0]
    assert missing == 0
    zh_missing = bank_con.execute(
        "SELECT COUNT(*) FROM facts WHERE track='qaqc' AND kind='term' AND coalesce(zh,'')=''").fetchone()[0]
    assert zh_missing == 0


# -- Inspect ------------------------------------------------------------------------------

def test_five_qaqc_checklists(bank_con):
    keys = export_checklist.qaqc_keys(bank_con)
    assert keys == ["cable_pull", "reel_receiving", "fiber_tier1", "cat6_cert", "ncr_closeout"]


def test_cable_pull_exports_docx_and_pdf(bank_con, tmp_path):
    written = export_checklist.export_qaqc(bank_con, "cable_pull", tmp_path, pdf=True)
    docx = [p for p in written if p.suffix == ".docx"]
    assert len(docx) == 1
    from docx import Document
    doc = Document(str(docx[0]))
    body = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert "Cable pull inspection" in body
    assert "[ ]" in cells and "https://" in body
    if export_checklist.soffice_path():
        pdfs = [p for p in written if p.suffix == ".pdf"]
        assert len(pdfs) == 1 and pdfs[0].stat().st_size > 1024
    for p in written:
        assert p.parent == tmp_path


# -- isolation: exam, shift, mastery, streak ---------------------------------------------

def test_osha_exam_draws_only_osha(game_con):
    from osha_game.game import compose
    con, _ = game_con
    every = list(range(1, 24)) + QAQC_IDS          # even if QA/QC ids leaked into "unlocked"
    for _ in range(5):
        qs = compose.exam_questions(con, every, size=30)
        assert len(qs) == 30
        assert {q["track"] for q in qs} == {"osha"}
        assert all(1 <= q["module_id"] <= 23 for q in qs)


def test_qaqc_shift_updates_only_qaqc(game_con):
    from osha_game.game import mastery, rules
    con, pid = game_con
    osha_before = mastery.all_mastery(con, pid, "osha")
    prof_before = dict(con.execute(
        "SELECT days_without_incident, best_streak, lifetime_score FROM profiles WHERE id=?", (pid,)).fetchone())

    shift = rules.Shift(con, pid, 104, size=6, track="qaqc")
    assert len(shift.questions) == 6
    assert all(q["track"] == "qaqc" and q["module_id"] == 104 for q in shift.questions)
    while not shift.done:
        shift.answer(shift.current["correct"])
    summary = shift.finish()
    assert summary["outcome"] == "clean" and summary["track"] == "qaqc"

    srs_qids = [r[0] for r in con.execute("SELECT qid FROM srs WHERE profile_id=?", (pid,))]
    tracks_seen = {r[0] for r in con.execute(
        f"SELECT DISTINCT track FROM bank.questions WHERE qid IN ({','.join('?' * len(srs_qids))})",
        srs_qids)}
    assert len(srs_qids) == 6 and tracks_seen == {"qaqc"}
    assert mastery.all_mastery(con, pid, "osha") == osha_before
    assert dict(con.execute(
        "SELECT days_without_incident, best_streak, lifetime_score FROM profiles WHERE id=?",
        (pid,)).fetchone()) == prof_before
    assert rules.track_streak(con, pid, "qaqc")["days_without_incident"] == 1
    assert mastery.module_mastery(con, pid, 104) > 0
    # the OSHA review queue does not see the QA/QC cards (they are due later anyway, but the
    # filter must hold even when due): force them due and check
    con.execute("UPDATE srs SET due='2000-01-01T00:00:00+00:00' WHERE profile_id=?", (pid,))
    from osha_game import srs as srsmod
    assert srsmod.due_count(con, pid, "osha") == 0
    assert srsmod.due_count(con, pid, "qaqc") == 6
    from osha_game.game import compose
    osha_shift = compose.shift_questions(con, pid, 1, size=10, track="osha")
    assert {q["track"] for q in osha_shift} == {"osha"}


# -- migration ---------------------------------------------------------------------------

_OLD_QUESTIONS = """CREATE TABLE questions(
  qid TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('mc','blank')), category TEXT NOT NULL,
  module_id INTEGER, lesson_id TEXT, prompt TEXT NOT NULL, correct TEXT NOT NULL,
  options TEXT NOT NULL, explanation TEXT, cfr TEXT, page INTEGER,
  source_doc TEXT NOT NULL DEFAULT 'guide' CHECK(source_doc IN ('guide','sds')),
  source_quote TEXT, origin TEXT NOT NULL);"""
_OLD_FACTS = """CREATE TABLE facts(
  fid TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, value TEXT NOT NULL,
  quote TEXT NOT NULL, page INTEGER NOT NULL, module_id INTEGER, lesson_id TEXT, cfr TEXT,
  number REAL, unit TEXT, source_doc TEXT NOT NULL DEFAULT 'guide');"""


def test_migration_keeps_osha_rows(tmp_path):
    """An old-schema bank migrates to the track-aware one with every OSHA row identical."""
    from osha_game import db
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(_OLD_QUESTIONS + _OLD_FACTS + """
      CREATE TABLE modules(id INTEGER PRIMARY KEY, title TEXT, topic TEXT, page_start INTEGER, page_end INTEGER);
      CREATE TABLE lessons(id TEXT PRIMARY KEY, module_id INTEGER, label TEXT);
      CREATE TABLE checklist_items(cid TEXT PRIMARY KEY, module_id INTEGER, seq INTEGER, text TEXT);
      CREATE TABLE scenarios(sid TEXT PRIMARY KEY, module_id INTEGER);
      CREATE VIRTUAL TABLE facts_fts USING fts5(subject, value, quote, fid UNINDEXED);
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);""")
    con.execute("INSERT INTO questions VALUES ('q1','mc','x',3,NULL,'p','c','[\"c\"]','e','1926.1',42,'guide','s','deterministic')")
    con.execute("INSERT INTO questions VALUES ('q2','blank','x',NULL,NULL,'p ____','c','[]',NULL,NULL,7,'sds',NULL,'gemini')")
    con.execute("INSERT INTO facts VALUES ('f1','term','A','B','C',5,3,NULL,NULL,NULL,NULL,'guide')")
    con.commit()
    con.close()

    con = db.bank_connect(path)
    before = qaqc.osha_snapshot(con)
    steps = qaqc.migrate_bank(con)
    assert any(s.startswith("questions") for s in steps) and any(s.startswith("facts") for s in steps)
    assert not qaqc.needs_migration(con)
    assert qaqc.osha_snapshot(con) == before
    assert [r[0] for r in con.execute("SELECT DISTINCT track FROM questions")] == ["osha"]
    assert qaqc.migrate_bank(con) == []          # idempotent
    con.close()


# -- headless dashboard: track picker -> Look Up -> Inspect -> QA/QC shift ----------------

def _correct_index(screen) -> int:
    q = screen.shift.current
    return screen._current_options.index(q["correct"]) + 1


def test_track_picker_playthrough(tmp_progress):
    from osha_game.ui.app import InspectorApp
    from osha_game.ui.screens.dashboard import DashboardScreen
    from osha_game.ui.screens.debrief import DebriefScreen
    from osha_game.ui.screens.home import HomeScreen
    from osha_game.ui.screens.inspect import InspectScreen
    from osha_game.ui.screens.lookup import LookupScreen
    from osha_game.ui.screens.plantmap import PlantMapScreen
    from osha_game.ui.screens.shift import ShiftScreen
    from osha_game.game import mastery

    async def body():
        app = InspectorApp()
        app.cfg["game"]["shift_size"] = 3
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
            assert app.state.track == "osha"
            assert "[ OSHA 30 ]" in text_of(app.screen.query_one("#track", Static))
            pid = app.state.profile_id
            osha_before = mastery.all_mastery(app.con, pid, "osha")

            await pilot.press("k")              # switch track
            await pilot.pause()
            assert app.state.track == "qaqc"
            assert "[ QA/QC ]" in text_of(app.screen.query_one("#track", Static))
            assert "QA/QC" in text_of(app.screen.query_one("#door-inspect", Static))

            # Look Up on the QA/QC track
            await pilot.press("2")
            await pilot.pause()
            assert isinstance(app.screen, LookupScreen)
            box = app.screen.query_one("#query", Input)
            box.value = "上鎖掛籤"
            await pilot.press("enter")
            await pilot.pause(0.2)
            detail = text_of(app.screen.query_one("#detail", Static))
            assert "上鎖掛籤" in detail and "Source:" in detail and "https://" in detail
            await pilot.press("escape")
            await pilot.pause()

            # Inspect lists the five QA/QC checklists; tick one cable-pull item
            await pilot.press("3")
            await pilot.pause()
            assert isinstance(app.screen, InspectScreen)
            lists = app.screen.query_one("#modules", OptionList)
            assert lists.option_count == 5
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.stage == "walk" and app.screen.list_key == "cable_pull"
            await pilot.press("space")
            await pilot.pause()
            assert app.con.execute("SELECT COUNT(*) FROM checklist_ticks").fetchone()[0] == 1
            assert "Source:" in text_of(app.screen.query_one("#detail", Static))
            await pilot.press("escape")
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

            # Train: QA/QC break room, plant map of six modules, no exam
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            assert "QA/QC" in text_of(app.screen.query_one("#title", Static))
            assert "6/6 modules unlocked" in text_of(app.screen.query_one("#unlocked-line", Static))
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)        # exam refused on QA/QC
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, PlantMapScreen)
            assert app.screen._module_ids == QAQC_IDS
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, ShiftScreen)
            assert app.screen.shift.track == "qaqc"
            for _ in range(3):
                await pilot.press(str(_correct_index(app.screen)))
                await pilot.pause(1.5)
            assert isinstance(app.screen, DebriefScreen)
            assert "QA/QC" in text_of(app.screen.query_one("#streak-label", Static))
            await pilot.press("enter")
            await pilot.pause()

            att = app.con.execute(
                "SELECT COUNT(*) FROM attempts a JOIN bank.questions q ON q.qid=a.qid "
                "WHERE q.track='qaqc'").fetchone()[0]
            assert att == 3
            assert app.con.execute(
                "SELECT COUNT(*) FROM attempts a JOIN bank.questions q ON q.qid=a.qid "
                "WHERE q.track='osha'").fetchone()[0] == 0
            assert mastery.all_mastery(app.con, pid, "osha") == osha_before
            row = app.con.execute("SELECT days_without_incident FROM profiles WHERE id=?", (pid,)).fetchone()
            assert row[0] == 0

            # back on the OSHA track everything reads as before
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)
            await pilot.press("k")
            await pilot.pause()
            assert app.state.track == "osha"
            await pilot.press("3")
            await pilot.pause()
            assert app.screen.query_one("#modules", OptionList).option_count == 23
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("q")

    run(body())
