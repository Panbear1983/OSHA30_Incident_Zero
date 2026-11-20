"""Chooses which questions go into a shift or an exam.

Priority for a shift: FSRS-due reviews first (spaced repetition doing its job), then new
(never-attempted) questions from the target module, then new questions from anywhere, then
-- only if a module is truly exhausted -- already-attempted questions not yet due. Within
each tier, order is randomized so the same module doesn't always open with the same card.
"""
import random
from . import mastery
from .. import srs as srsmod


def _bank_rows(con, track: str = "osha") -> dict[str, "sqlite3.Row"]:
    return {r["qid"]: r for r in con.execute(
        "SELECT * FROM bank.questions WHERE track=?", (track,)).fetchall()}


def _take(pool: list, seen: set, chosen: list, need: int) -> None:
    random.shuffle(pool)
    for r in pool:
        if need <= 0:
            return
        if r["qid"] in seen:
            continue
        chosen.append(r)
        seen.add(r["qid"])
        need -= 1


def shift_questions(con, profile_id: int, module_id: int | None, size: int = 15,
                    track: str = "osha") -> list:
    """Same priority rules for every track (FSRS-due, then new in the module, then new
    anywhere, then not-yet-due), but only ever drawn from `track`'s questions."""
    all_rows = _bank_rows(con, track)
    attempted = srsmod.attempted_qids(con, profile_id)
    due = [q for q in srsmod.due_qids(con, profile_id, limit=size, track=track) if q in all_rows]

    chosen: list = []
    seen: set = set()
    _take([all_rows[q] for q in due], seen, chosen, size - len(chosen))

    if module_id is not None:
        module_new = [r for r in all_rows.values()
                      if r["module_id"] == module_id and r["qid"] not in attempted]
        _take(module_new, seen, chosen, size - len(chosen))

    any_new = [r for r in all_rows.values() if r["qid"] not in attempted]
    _take(any_new, seen, chosen, size - len(chosen))

    leftover = list(all_rows.values())
    _take(leftover, seen, chosen, size - len(chosen))

    random.shuffle(chosen)
    return chosen[:size]


def exam_questions(con, unlocked_module_ids: list[int], size: int = 30) -> list:
    """Stratified across unlocked modules via round-robin, so no module dominates.
    The mock exam is the OSHA 30 exam: only OSHA-track questions can ever be drawn."""
    all_rows = [r for r in con.execute(
                    "SELECT * FROM bank.questions WHERE track='osha'").fetchall()
                if r["module_id"] in unlocked_module_ids]
    by_mod: dict[int, list] = {}
    for r in all_rows:
        by_mod.setdefault(r["module_id"], []).append(r)
    for pool in by_mod.values():
        random.shuffle(pool)

    mods = list(by_mod.keys())
    random.shuffle(mods)
    chosen: list = []
    seen: set = set()
    i = 0
    while len(chosen) < size and mods:
        mod = mods[i % len(mods)]
        pool = by_mod[mod]
        if not pool:
            mods.remove(mod)
            if mods:
                i %= len(mods)
            continue
        r = pool.pop()
        if r["qid"] not in seen:
            chosen.append(r)
            seen.add(r["qid"])
        i += 1
    random.shuffle(chosen)
    return chosen[:size]
