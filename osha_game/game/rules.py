"""The shift state machine: confidence bet, near-miss retry, incident detection, and the
streak/score bookkeeping that makes losing legible. This is the one place that defines
what "winning" and "losing" a question means.

Flow per question:
  answer(chosen, bet)
    correct                -> 'hit' (or 'near_miss' if this was the retry after a miss)
    wrong, bet             -> immediate 'incident' (betting forfeits the retry)
    wrong, first try, no bet -> 'near_miss_pending': question stays current, call retry()
  retry(chosen)             -> 'near_miss' if now correct, else 'incident'
"""
import json
from datetime import datetime, timezone
from . import compose
from .. import srs as srsmod

POINTS = {"hit": 10, "near_miss": 4, "incident": 0}
BET_MULTIPLIER = 2


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _col(row, name: str):
    """Column value, or None on a row from a bank that predates the column."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


def track_streak(con, profile_id: int, track: str) -> dict:
    """{days_without_incident, best_streak, lifetime_score} for a non-OSHA track (zeros if
    the profile has never finished a shift on it). OSHA's live in `profiles`."""
    row = con.execute(
        "SELECT days_without_incident, best_streak, lifetime_score FROM track_streaks "
        "WHERE profile_id=? AND track=?", (profile_id, track),
    ).fetchone()
    if row is None:
        return {"days_without_incident": 0, "best_streak": 0, "lifetime_score": 0}
    return dict(row)


class Outcome:
    def __init__(self, result: str, correct: bool, score_delta: int, incident: dict | None = None):
        self.result = result
        self.correct = correct
        self.score_delta = score_delta
        self.incident = incident


class Shift:
    def __init__(self, con, profile_id: int, module_id: int | None, size: int = 15,
                 track: str = "osha"):
        self.con = con
        self.profile_id = profile_id
        self.module_id = module_id
        self.track = track
        self.questions = compose.shift_questions(con, profile_id, module_id, size, track=track)
        self.index = 0
        self.score = 0
        self.correct_count = 0
        self.near_miss_count = 0
        self.incident_count = 0
        self.incidents: list[dict] = []
        self.near_misses: list[dict] = []
        self.started_at = datetime.now(timezone.utc)
        cur = con.execute(
            "INSERT INTO shifts (profile_id, module_id, started_at, questions) VALUES (?,?,?,?)",
            (profile_id, module_id, self.started_at.isoformat(), len(self.questions)),
        )
        self.shift_id = cur.lastrowid
        con.commit()

    @property
    def current(self):
        return self.questions[self.index] if self.index < len(self.questions) else None

    @property
    def done(self) -> bool:
        return self.index >= len(self.questions)

    def answer(self, chosen: str, bet: bool = False, ms: int | None = None) -> Outcome:
        return self._answer(chosen, bet, ms, is_retry=False)

    def retry(self, chosen: str, ms: int | None = None) -> Outcome:
        return self._answer(chosen, bet=False, ms=ms, is_retry=True)

    def _answer(self, chosen: str, bet: bool, ms: int | None, is_retry: bool) -> Outcome:
        q = self.current
        if q is None:
            raise RuntimeError("no current question -- shift already finished")
        is_correct = _norm(chosen) == _norm(q["correct"])

        if is_correct:
            result = "near_miss" if is_retry else "hit"
            delta = POINTS[result] * (BET_MULTIPLIER if (bet and result == "hit") else 1)
            self.score += delta
            if result == "hit":
                self.correct_count += 1
            else:
                self.near_miss_count += 1
                self.near_misses.append({"qid": q["qid"], "prompt": q["prompt"]})
            self._record_attempt(q, chosen, result, bet, ms)
            srsmod.review(self.con, self.profile_id, q["qid"], result, bet=bet)
            self.index += 1
            return Outcome(result, True, delta)

        if is_retry or bet:
            self.incident_count += 1
            report = {
                "qid": q["qid"], "prompt": q["prompt"], "chosen": chosen,
                "correct": q["correct"], "explanation": q["explanation"],
                "cfr": q["cfr"], "page": q["page"], "source_quote": q["source_quote"],
                "category": q["category"],
                "source_label": _col(q, "source_label"), "source_url": _col(q, "source_url"),
            }
            self.incidents.append(report)
            self._record_attempt(q, chosen, "incident", bet, ms)
            srsmod.review(self.con, self.profile_id, q["qid"], "incident", bet=bet)
            self.index += 1
            return Outcome("incident", False, 0, incident=report)

        return Outcome("near_miss_pending", False, 0)

    def _record_attempt(self, q, chosen: str, result: str, bet: bool, ms: int | None) -> None:
        self.con.execute(
            "INSERT INTO attempts (profile_id, shift_id, qid, at, chosen, result, bet, ms) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.profile_id, self.shift_id, q["qid"], datetime.now(timezone.utc).isoformat(),
             chosen, result, int(bet), ms),
        )

    def finish(self) -> dict:
        outcome = "clean" if self.incident_count == 0 else "incident"
        self.con.execute(
            "UPDATE shifts SET ended_at=?, correct=?, near_misses=?, incidents=?, score=?, outcome=? "
            "WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), self.correct_count, self.near_miss_count,
             self.incident_count, self.score, outcome, self.shift_id),
        )
        if self.track == "osha":
            row = self.con.execute(
                "SELECT days_without_incident, best_streak FROM profiles WHERE id=?", (self.profile_id,)
            ).fetchone()
            new_streak = row["days_without_incident"] + 1 if outcome == "clean" else 0
            best = max(row["best_streak"], new_streak)
            self.con.execute(
                "UPDATE profiles SET days_without_incident=?, best_streak=?, "
                "lifetime_score=lifetime_score+?, last_seen_at=? WHERE id=?",
                (new_streak, best, self.score, datetime.now(timezone.utc).isoformat(), self.profile_id),
            )
        else:
            # Any other track keeps its own streak; the OSHA numbers in `profiles` are not touched.
            row = track_streak(self.con, self.profile_id, self.track)
            new_streak = row["days_without_incident"] + 1 if outcome == "clean" else 0
            best = max(row["best_streak"], new_streak)
            self.con.execute(
                "INSERT INTO track_streaks (profile_id, track, days_without_incident, best_streak, "
                " lifetime_score) VALUES (?,?,?,?,?) ON CONFLICT(profile_id, track) DO UPDATE SET "
                " days_without_incident=excluded.days_without_incident, best_streak=excluded.best_streak, "
                " lifetime_score=track_streaks.lifetime_score+?",
                (self.profile_id, self.track, new_streak, best, self.score, self.score),
            )
        self.con.commit()
        return {
            "outcome": outcome, "score": self.score, "streak": new_streak, "best_streak": best,
            "track": self.track,
            "correct": self.correct_count, "near_misses": self.near_miss_count,
            "incidents": self.incident_count, "incident_reports": self.incidents,
            "near_miss_log": self.near_misses,
        }

    def abandon(self) -> None:
        self.con.execute(
            "UPDATE shifts SET ended_at=?, correct=?, near_misses=?, incidents=?, score=?, "
            "outcome='abandoned' WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), self.correct_count, self.near_miss_count,
             self.incident_count, self.score, self.shift_id),
        )
        self.con.commit()


class Exam:
    """A timed mock exam: no per-question feedback, no bet, no near-miss retry -- answer
    and move on, score revealed only at the end."""

    def __init__(self, con, profile_id: int, unlocked_module_ids: list[int], size: int = 30):
        self.con = con
        self.profile_id = profile_id
        self.questions = compose.exam_questions(con, unlocked_module_ids, size)
        self.answers: list[dict] = []
        self.started_at = datetime.now(timezone.utc)

    @property
    def total(self) -> int:
        return len(self.questions)

    def answer(self, index: int, chosen: str) -> bool:
        q = self.questions[index]
        correct = _norm(chosen) == _norm(q["correct"])
        self.answers.append({
            "qid": q["qid"], "module_id": q["module_id"], "prompt": q["prompt"],
            "chosen": chosen, "correct_answer": q["correct"], "correct": correct,
            "explanation": q["explanation"], "cfr": q["cfr"], "page": q["page"],
        })
        return correct

    def finish(self, pass_pct: float = 70.0, duration_s: int | None = None) -> dict:
        total = len(self.questions)
        correct = sum(1 for a in self.answers if a["correct"])
        pct = (100.0 * correct / total) if total else 0.0
        passed = pct >= pass_pct

        by_module: dict[int, dict] = {}
        for a in self.answers:
            mid = a["module_id"]
            slot = by_module.setdefault(mid, {"correct": 0, "total": 0})
            slot["total"] += 1
            if a["correct"]:
                slot["correct"] += 1

        detail_json = json.dumps(self.answers)
        self.con.execute(
            "INSERT INTO exams (profile_id, at, duration_s, total, correct, passed, detail) "
            "VALUES (?,?,?,?,?,?,?)",
            (self.profile_id, datetime.now(timezone.utc).isoformat(), duration_s,
             total, correct, int(passed), detail_json),
        )
        self.con.commit()
        return {
            "passed": passed, "correct": correct, "total": total, "pct": pct,
            "by_module": by_module, "answers": self.answers,
        }
