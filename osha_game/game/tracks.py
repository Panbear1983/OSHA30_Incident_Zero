"""The two study tracks the app holds, and how to name their modules.

  osha  the OSHA 30 course: modules 1-23, study-guide page citations, mock exam
  qaqc  the QA/QC pre-start program: modules 101-106 (shown as Q1-Q6), web-source citations,
        no exam

The tracks share the FSRS scheduler and the shift game, but each one only ever sees its
own questions, mastery, streak and stats (see compose.py, srs.py, rules.Shift.finish).
"""
from ..content.segment import TITLES as OSHA_TITLES, TOPICS as OSHA_TOPICS

TRACKS = ("osha", "qaqc")
NAMES = {"osha": "OSHA 30", "qaqc": "QA/QC"}
BLURB = {
    "osha": "OSHA 30 Construction: 23 modules, study-guide pages, mock exam",
    "qaqc": "QA/QC pre-start: 6 modules (cabling, fiber, power, safety, site), web sources",
}


def track_of_module(module_id) -> str:
    return "qaqc" if module_id is not None and int(module_id) >= 101 else "osha"


def label(module_id) -> str:
    """'M07' for OSHA, 'Q3' for QA/QC."""
    if module_id is None:
        return "M??"
    mid = int(module_id)
    return f"Q{mid - 100}" if mid >= 101 else f"M{mid:02d}"


def topic(module_id) -> str:
    if module_id is None:
        return ""
    mid = int(module_id)
    if mid >= 101:
        from ..content.qaqc import TOPICS
        return TOPICS.get(mid, f"Module {label(mid)}")
    return OSHA_TOPICS.get(mid, f"Module {mid}")


def title(module_id) -> str:
    if module_id is None:
        return ""
    mid = int(module_id)
    if mid >= 101:
        from ..content.qaqc import TITLES
        return TITLES.get(mid, f"Module {label(mid)}")
    return OSHA_TITLES.get(mid, f"Module {mid}")


def other(track: str) -> str:
    return "qaqc" if track == "osha" else "osha"


def has_track(con, track: str, schema: str = "bank.") -> bool:
    """True when the bank holds at least one question for `track` (QA/QC needs
    './dashboard.sh qaqc build' once)."""
    try:
        return con.execute(
            f"SELECT 1 FROM {schema}questions WHERE track=? LIMIT 1", (track,)).fetchone() is not None
    except Exception:
        return track == "osha"


def shift_module_clause(track: str) -> str:
    """SQL condition on shifts.module_id selecting one track's shifts."""
    return "module_id >= 101" if track == "qaqc" else "(module_id IS NULL OR module_id < 101)"


def attempt_qid_clause(track: str) -> str:
    """SQL condition on attempts.qid / srs.qid selecting one track. OSHA keeps attempts on
    questions that have since left the bank, exactly as before the QA/QC track existed."""
    if track == "osha":
        return "qid NOT IN (SELECT qid FROM bank.questions WHERE track <> 'osha')"
    return "qid IN (SELECT qid FROM bank.questions WHERE track = 'qaqc')"
