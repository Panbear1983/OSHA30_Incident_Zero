"""FSRS scheduling glue: one Card per (profile_id, qid), persisted as JSON in progress.db.

Rating mapping is the game's whole point: how you did on a question decides when it
comes back. A confidence bet paid off is rated Easy; a plain hit is Good; surviving a
near miss is Hard (you needed a second look); a full incident is Again.
"""
from datetime import datetime, timezone
from fsrs import Scheduler, Card, Rating

_scheduler = Scheduler(desired_retention=0.9, enable_fuzzing=True)

RATING_FOR_RESULT = {
    "incident": Rating.Again,
    "near_miss": Rating.Hard,
    "hit": Rating.Good,
    "hit_bet": Rating.Easy,
}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def get_or_create(con, profile_id: int, qid: str) -> Card:
    row = con.execute("SELECT card_json FROM srs WHERE profile_id=? AND qid=?", (profile_id, qid)).fetchone()
    if row:
        return Card.from_json(row["card_json"])
    return Card()


def review(con, profile_id: int, qid: str, result: str, bet: bool = False) -> Card:
    """result in {'hit','near_miss','incident'}; bet=True upgrades a hit to Easy."""
    key = "hit_bet" if (result == "hit" and bet) else result
    rating = RATING_FOR_RESULT[key]
    card = get_or_create(con, profile_id, qid)
    new_card, _log = _scheduler.review_card(card, rating)

    exists = con.execute("SELECT 1 FROM srs WHERE profile_id=? AND qid=?", (profile_id, qid)).fetchone()
    lapses_inc = 1 if rating == Rating.Again else 0
    args_common = (
        new_card.due.isoformat(), int(new_card.state), new_card.stability,
        new_card.difficulty, _iso(new_card.last_review), lapses_inc, new_card.to_json(),
    )
    if exists:
        con.execute(
            "UPDATE srs SET due=?, state=?, stability=?, difficulty=?, last_review=?, "
            " reps=reps+1, lapses=lapses+?, card_json=? WHERE profile_id=? AND qid=?",
            args_common + (profile_id, qid),
        )
    else:
        con.execute(
            "INSERT INTO srs (profile_id, qid, due, state, stability, difficulty, "
            " last_review, reps, lapses, card_json) VALUES (?,?,?,?,?,?,?,1,?,?)",
            (profile_id, qid, new_card.due.isoformat(), int(new_card.state), new_card.stability,
             new_card.difficulty, _iso(new_card.last_review), lapses_inc, new_card.to_json()),
        )
    return new_card


def retrievability(con, profile_id: int, qid: str) -> float:
    row = con.execute("SELECT card_json FROM srs WHERE profile_id=? AND qid=?", (profile_id, qid)).fetchone()
    if not row:
        return 0.0
    return _scheduler.get_card_retrievability(Card.from_json(row["card_json"]))


def _track_clause(track: str) -> tuple[str, tuple]:
    """SQL filter on srs.qid for one track. OSHA keeps cards whose question has left the bank
    (exactly the pre-QA/QC behaviour); any other track counts only its own questions."""
    if track == "osha":
        return " AND qid NOT IN (SELECT qid FROM bank.questions WHERE track <> 'osha')", ()
    return " AND qid IN (SELECT qid FROM bank.questions WHERE track = ?)", (track,)


def due_qids(con, profile_id: int, limit: int = 8, track: str | None = None) -> list[str]:
    """Due cards, earliest first. With `track`, cards belonging to another track's questions
    are left out before the limit is applied, so a QA/QC review can never take an OSHA
    shift's slot (or the other way round)."""
    now = datetime.now(timezone.utc).isoformat()
    if track is None:
        rows = con.execute(
            "SELECT qid FROM srs WHERE profile_id=? AND due<=? ORDER BY due LIMIT ?",
            (profile_id, now, limit),
        ).fetchall()
    else:
        clause, extra = _track_clause(track)
        rows = con.execute(
            f"SELECT qid FROM srs WHERE profile_id=? AND due<=?{clause} ORDER BY due LIMIT ?",
            (profile_id, now, *extra, limit),
        ).fetchall()
    return [r["qid"] for r in rows]


def due_count(con, profile_id: int, track: str = "osha") -> int:
    """How many cards of this track are due now."""
    clause, extra = _track_clause(track)
    return con.execute(
        f"SELECT COUNT(*) FROM srs WHERE profile_id=? AND due<=?{clause}",
        (profile_id, datetime.now(timezone.utc).isoformat(), *extra),
    ).fetchone()[0]


def attempted_qids(con, profile_id: int) -> set[str]:
    rows = con.execute("SELECT qid FROM srs WHERE profile_id=?", (profile_id,)).fetchall()
    return {r["qid"] for r in rows}
