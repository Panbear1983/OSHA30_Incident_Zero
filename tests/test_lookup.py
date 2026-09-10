"""Phase 2 check: ten common questions return the right fact first (or in the top 3 where
the guide states the same number in several places)."""
import pytest

from osha_game.lookup import search as srch

CASES = [
    # query,                              expected in top hit (subject or value substring), max rank
    ("guardrail height",                  "42 inches", 1),
    ("how many days to report a fatality", "8 hours", 1),
    ("hospitalization report",            "24 hours", 1),
    ("fixed ladder cage",                 "24 feet", 1),
    ("lockout tagout",                    "Lockout", 1),
    ("noise exposure decibels",           "85 dBA", 1),
    ("SDS section first aid",             "Section 4", 1),
    ("stair rail height",                 "42 inches", 3),
    ("1910.95",                           "1910.95", 1),
    ("permit space entry supervisor",     "entry supervisor", 3),
]


@pytest.mark.parametrize("query,expected,max_rank", CASES)
def test_common_questions(bank_con, query, expected, max_rank):
    hits = srch.search(bank_con, query, limit=5)
    assert hits, f"no hits for {query!r}"
    top = hits[:max_rank]
    assert any(expected.lower() in (h["subject"] + " " + h["value"]).lower() for h in top), \
        f"{query!r}: expected {expected!r} in top {max_rank}, got " + \
        "; ".join(h["subject"] + " | " + h["value"][:60] for h in top)


def test_every_hit_cites_a_page(bank_con):
    for h in srch.search(bank_con, "ladder", limit=25):
        assert h["page"] >= 1 and h["quote"]


def test_kind_filter(bank_con):
    hits = srch.search(bank_con, "confined space", kind="term", limit=10)
    assert hits and all(h["kind"] == "term" for h in hits)


def test_empty_query(bank_con):
    assert srch.search(bank_con, "the of a") == []


def test_fact_counts(bank_con):
    total = bank_con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    kinds = {r[0] for r in bank_con.execute("SELECT DISTINCT kind FROM facts")}
    assert total >= 1400
    assert kinds == set(srch.KINDS)
    fts = bank_con.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
    assert fts == total
