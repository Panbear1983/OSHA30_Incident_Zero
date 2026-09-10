"""Headless Textual Pilot playthrough: roster -> new profile -> splash -> dashboard ->
Look Up (search, pick) -> back -> Train (Break Room) -> back -> quit."""
from textual.widgets import Input, OptionList, Static

from conftest import run, text_of


def test_dashboard_and_lookup(tmp_progress):
    from osha_game.ui.app import InspectorApp
    from osha_game.ui.screens.dashboard import DashboardScreen
    from osha_game.ui.screens.home import HomeScreen
    from osha_game.ui.screens.lookup import LookupScreen

    async def body():
        app = InspectorApp()
        async with app.run_test(size=(120, 40)) as pilot:
            # roster: add a profile
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
            glance = text_of(app.screen.query_one("#glance", Static))
            assert "facts" in glance

            # Look Up
            await pilot.press("2")
            await pilot.pause()
            assert isinstance(app.screen, LookupScreen)
            box = app.screen.query_one("#query", Input)
            box.value = "guardrail height"
            await pilot.press("enter")
            await pilot.pause(0.2)
            results = app.screen.query_one("#results", OptionList)
            assert results.option_count > 0
            assert results.highlighted == 0
            detail = text_of(app.screen.query_one("#detail", Static))
            assert "42 inches" in detail and "p." in detail
            await pilot.press("down")
            await pilot.pause()
            assert results.highlighted == 1
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

            # Train door still leads to the unchanged Break Room, and back
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

            # nothing was written to progress beyond the profile
            n = app.con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            assert n == 0
            await pilot.press("q")

    run(body())
