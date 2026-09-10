"""Phase 4 checks: one deterministic scenario per lesson, every quoted answer line is on its
cited page, the Ollama grounding verifier rejects invented facts (no Ollama needed), and a
headless Pilot playthrough of the Interview screen writes exactly one self-rating."""
import json

from textual.widgets import OptionList, Static

from conftest import run, text_of
from osha_game import paths
from osha_game.content import llm_gen
from osha_game.content.extract import load_pages
from osha_game.content.norm import loose
from osha_game.content.scenarios import ANSWER_KEYS


def test_one_deterministic_scenario_per_lesson(bank_con):
    n_lessons = bank_con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    rows = bank_con.execute(
        "SELECT lesson_id, prompt, answer_json FROM scenarios WHERE origin='deterministic'"
    ).fetchall()
    assert n_lessons == 56
    assert len(rows) == n_lessons
    assert len({r["lesson_id"] for r in rows}) == n_lessons
    for r in rows:
        assert len(r["prompt"]) > 80
        data = json.loads(r["answer_json"])
        assert set(ANSWER_KEYS) <= set(data)
        assert data["steps"] and len(data["steps"]) == 3
        assert any(data[k] for k in ("standards", "numbers", "terms", "rules"))


def test_every_answer_line_is_on_its_page(bank_con):
    guide = load_pages(paths.PAGES_GUIDE)
    sds = load_pages(paths.PAGES_SDS)
    page_cache = {("guide", i): loose(t) for i, t in enumerate(guide, start=1)}
    page_cache.update({("sds", i): loose(t) for i, t in enumerate(sds, start=1)})
    checked = 0
    for r in bank_con.execute("SELECT answer_json FROM scenarios").fetchall():
        data = json.loads(r["answer_json"])
        for key in ("standards", "numbers", "terms", "rules"):
            for e in data[key]:
                quote = e.get("text") or e.get("definition")
                page = e["page"]
                needle = loose(quote)[:60]
                doc = "sds" if "Safety Data Sheet" in quote and page <= 10 else "guide"
                assert needle in page_cache[(doc, page)], f"{key} entry not on p.{page}: {quote[:80]}"
                checked += 1
    assert checked > 200


def test_grounding_verifier_without_ollama():
    subjects = ["Guardrail System", "42 inches", "29 CFR 1910.29"]
    cites = ["1910.29"]
    good = (
        "You are walking the mezzanine when you notice the guardrail system along the open "
        "edge looks low. A worker mentions the top rail was rebuilt last week and nobody "
        "measured it against the 42 inches the guide requires. The area supervisor points "
        "to 29 CFR 1910.29 and asks whether the crew can keep working near the edge today. "
        "What applies here, and what do you do first, second, and third?"
    )
    ok, why = llm_gen.verify(good, subjects, cites)
    assert ok, why

    bad_number = good.replace("42 inches", "39 inches")
    ok, why = llm_gen.verify(bad_number, subjects, cites)
    assert not ok and "invented number" in why

    bad_cite = good.replace("29 CFR 1910.29", "29 CFR 1910.147")
    ok, why = llm_gen.verify(bad_cite, subjects, cites)
    assert not ok and "invented standard" in why

    too_vague = "You see something unsafe near an edge. What applies here, and what do you do first, second, and third?"
    ok, why = llm_gen.verify(too_vague * 2, subjects, cites)
    assert not ok


def test_interview_playthrough(tmp_progress):
    from osha_game.ui.app import InspectorApp
    from osha_game.ui.screens.dashboard import DashboardScreen
    from osha_game.ui.screens.interview import InterviewScreen

    async def body():
        app = InspectorApp()
        async with app.run_test(size=(120, 45)) as pilot:
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

            await pilot.press("4")
            await pilot.pause()
            assert isinstance(app.screen, InterviewScreen)
            picker = app.screen.query_one("#picker", OptionList)
            assert picker.option_count == 24 and picker.highlighted == 0
            await pilot.press("down")           # module 1
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(0.2)
            prompt = text_of(app.screen.query_one("#prompt", Static))
            assert "first, second, and third" in prompt
            assert "hidden" in app.screen.query_one("#answer").classes

            await pilot.press("space")          # reveal
            await pilot.pause(0.2)
            assert "hidden" not in app.screen.query_one("#answer").classes
            headers = [text_of(w) for w in app.screen.query(".section-header")]
            assert "SUGGESTED STEPS" in headers

            await pilot.press("2")              # rate okay
            await pilot.pause(0.2)
            rows = app.con.execute("SELECT sid, rating FROM interview_ratings").fetchall()
            assert len(rows) == 1 and rows[0]["rating"] == 2
            # rating never touches the game's tables
            assert app.con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
            assert app.con.execute("SELECT COUNT(*) FROM srs").fetchone()[0] == 0

            await pilot.press("escape")         # back to picker
            await pilot.pause()
            assert isinstance(app.screen, InterviewScreen)
            assert "hidden" not in app.screen.query_one("#picker").classes
            await pilot.press("escape")         # back to dashboard
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)
            await pilot.press("q")

    run(body())
