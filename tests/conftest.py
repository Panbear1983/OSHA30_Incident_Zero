"""Shared fixtures. Every test runs against a throwaway progress.db so nobody's real
profile is ever touched; the committed bank.db is read as-is."""
import asyncio
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from osha_game import paths  # noqa: E402


@pytest.fixture
def tmp_progress(tmp_path, monkeypatch):
    """Point the game at a fresh progress.db under tmp_path."""
    db_path = tmp_path / "progress.db"
    monkeypatch.setattr(paths, "PROGRESS_DB", db_path)
    return db_path


@pytest.fixture
def bank_con():
    from osha_game import db
    con = db.bank_connect(paths.BANK_DB)
    yield con
    con.close()


def run(coro):
    """Run an async Textual Pilot test body from a plain sync test."""
    return asyncio.run(coro)


def text_of(widget) -> str:
    """Plain text of a Static regardless of whether it holds a str, Rich Text, or Content."""
    c = widget.content
    return c.plain if hasattr(c, "plain") else str(c)
