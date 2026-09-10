"""Drive the dashboard headlessly and save an SVG screenshot of each screen into
docs/screenshots/. Runs against a throwaway progress.db so no real profile is touched.

    venv/bin/python scripts/screenshots.py
"""
import asyncio
import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from osha_game import paths  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
SIZE = (120, 38)
NAME = "Inspector"


async def _type(pilot, text: str) -> None:
    for ch in text:
        await pilot.press("space" if ch == " " else ch)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="osha30-shots-"))
    paths.PROGRESS_DB = tmp / "progress.db"

    from osha_game.ui.app import InspectorApp
    from textual.widgets import Input

    app = InspectorApp()
    app.cfg["ui"]["animations"] = False
    async with app.run_test(size=SIZE) as pilot:
        def shot(name: str) -> None:
            app.save_screenshot(f"{name}.svg", path=str(OUT))
            print("wrote", OUT / f"{name}.svg")

        await pilot.press("n")
        await pilot.pause()
        await _type(pilot, NAME)
        await pilot.pause()
        shot("01_roster")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause(0.3)
        await pilot.press("space")
        await pilot.pause(0.3)
        shot("02_dashboard")

        # Look Up
        await pilot.press("2")
        await pilot.pause()
        app.screen.query_one("#query", Input).value = "hospitalization report"
        await pilot.press("enter")
        await pilot.pause(0.3)
        shot("03_lookup")
        await pilot.press("escape")
        await pilot.pause()

        # Inspect (if built)
        if importlib.util.find_spec("osha_game.ui.screens.inspect"):
            await pilot.press("3")
            await pilot.pause(0.3)
        if type(app.screen).__name__ == "InspectScreen":
            shot("04_inspect_pick")
            await pilot.press("enter")
            await pilot.pause(0.3)
            await pilot.press("space")
            await pilot.press("down")
            await pilot.press("space")
            await pilot.press("down")
            await pilot.pause(0.3)
            shot("05_inspect_walk")
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        # Interview (if built)
        if importlib.util.find_spec("osha_game.ui.screens.interview"):
            await pilot.press("4")
            await pilot.pause(0.3)
        if type(app.screen).__name__ == "InterviewScreen":
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause(0.3)
            shot("06_interview_prompt")
            await pilot.press("space")
            await pilot.pause(0.3)
            shot("07_interview_answer")
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        # Train
        await pilot.press("1")
        await pilot.pause(0.3)
        shot("08_train_breakroom")
        await pilot.press("m")
        await pilot.pause(0.3)
        shot("09_train_plantmap")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause(0.5)
        shot("10_train_shift")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        await pilot.press("q")


if __name__ == "__main__":
    asyncio.run(main())
