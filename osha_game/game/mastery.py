"""Module mastery = coverage times retention -- one honest number per plant-map tile.

An unattempted question counts as 0 retrievability, so a module with 50 questions and
5 confidently-known ones sits low until real coverage builds up, not just early luck.
"""
from .. import srs as srsmod

TILE_BANDS = (
    (0, "locked"),
    (15, "weak"),
    (40, "shaky"),
    (65, "solid"),
    (85, "strong"),
)


def module_mastery(con, profile_id: int, module_id: int) -> float:
    qids = [r["qid"] for r in con.execute(
        "SELECT qid FROM bank.questions WHERE module_id=?", (module_id,)
    ).fetchall()]
    if not qids:
        return 0.0
    total = sum(srsmod.retrievability(con, profile_id, q) for q in qids)
    return 100.0 * total / len(qids)


def all_mastery(con, profile_id: int) -> dict[int, float]:
    mod_ids = [r["id"] for r in con.execute("SELECT id FROM bank.modules ORDER BY id").fetchall()]
    return {m: module_mastery(con, profile_id, m) for m in mod_ids}


def clean_shift_count(con, profile_id: int, module_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM shifts WHERE profile_id=? AND module_id=? AND outcome='clean'",
        (profile_id, module_id),
    ).fetchone()[0]


def module_unlocked(con, profile_id: int, module_id: int) -> bool:
    if module_id <= 1:
        return True
    prior = module_id - 1
    if clean_shift_count(con, profile_id, prior) >= 1:
        return True
    return module_mastery(con, profile_id, prior) >= 30.0


def unlocked_modules(con, profile_id: int) -> list[int]:
    mod_ids = [r["id"] for r in con.execute("SELECT id FROM bank.modules ORDER BY id").fetchall()]
    return [m for m in mod_ids if module_unlocked(con, profile_id, m)]


def exam_unlocked(con, profile_id: int) -> bool:
    mod_ids = [r["id"] for r in con.execute("SELECT id FROM bank.modules ORDER BY id").fetchall()]
    if not mod_ids:
        return False
    unlocked = len(unlocked_modules(con, profile_id))
    return unlocked >= max(1, round(len(mod_ids) * 19 / 23))


def band_for(pct: float, locked: bool = False) -> str:
    if locked:
        return "locked"
    label = "weak"
    for threshold, name in TILE_BANDS:
        if pct >= threshold:
            label = name
    return label
