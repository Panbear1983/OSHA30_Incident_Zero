"""Search the fact base: type words, get facts ranked, each with its number / regulation /
page. Backed by the FTS5 index built alongside `facts` (porter stemming, so "ladders"
finds "ladder").

Works on either connection style the app uses:
  - a bank-only connection (CLI):  search(con, "guardrail height")
  - the game connection, where bank.db is ATTACHed as `bank`:  search(con, ..., schema="bank.")
"""
import re
import sqlite3

from ..content.segment import TOPICS

KINDS = ("term", "threshold", "deadline", "cfr", "rule", "sds")

KIND_LABEL = {
    "term": "TERM", "threshold": "NUMBER", "deadline": "DEADLINE",
    "cfr": "STANDARD", "rule": "RULE", "sds": "SDS",
}

# Ranking prior: specific, single-fact kinds first; the (many) rule sentences after.
_KIND_PENALTY = {"term": 0.0, "threshold": 0.0, "deadline": 0.0, "cfr": 0.0, "sds": 0.0, "rule": 2.0}

_STOP = {
    "a", "an", "the", "of", "to", "in", "on", "for", "is", "are", "be", "and", "or", "what",
    "whats", "what's", "how", "many", "much", "long", "do", "does", "i", "you", "need", "should",
    "must", "when", "which", "with", "by", "at", "from", "it", "its", "this", "that", "there",
    "about", "any", "required", "requirement", "requirements", "rule", "rules", "osha",
}

_SYN = {
    "ft": "feet", "foot": "feet", "inch": "inches", "in.": "inches", "lb": "pounds",
    "lbs": "pounds", "pound": "pounds", "hr": "hours", "hrs": "hours", "hour": "hours",
    "yr": "years", "yrs": "years", "year": "years", "day": "days", "%": "percent",
    "°f": "f", "db": "dba", "decibel": "dba", "decibels": "dba",
}

_TOKEN = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[A-Za-z][A-Za-z'\-]*|%|°f", re.I)

# Unit words are the asker's guess at the answer's shape ("how many DAYS..."), not something
# the fact must contain -- a fatality is reported in hours. They only nudge the ranking.
_SOFT = {"feet", "inches", "pounds", "hours", "days", "years", "degrees", "percent", "ppm",
         "dba", "volts", "amperes", "psi", "f", "report", "reported", "notify", "within"}
# soft token -> unit family stored on threshold/deadline facts; a matching numeric fact is
# what someone asking "how many <unit>" wants, so it gets a strong nudge.
_SOFT_UNIT = {"feet": "feet", "inches": "inches", "pounds": "pounds", "hours": "hours",
              "days": "days", "years": "years", "degrees": "degrees", "f": "degrees",
              "percent": "percent", "ppm": "ppm", "dba": "db", "volts": "volts",
              "amperes": "amperes", "psi": "psi"}
# Someone who asks "how many days" is happy with an answer in hours (a fatality is reported
# within 8 hours), and "how many feet" with one in inches -- so units are matched by group.
_UNIT_GROUP = {"hours": "time", "days": "time", "years": "time", "feet": "length", "inches": "length"}


def _group(unit: str | None) -> str | None:
    if unit is None:
        return None
    return _UNIT_GROUP.get(unit, unit)


def tokens(query: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.finditer(query):
        t = m.group(0).lower().strip("'-")
        t = _SYN.get(t, t)
        if not t or t in _STOP:
            continue
        out.append(t)
    return out


def split_hard_soft(toks: list[str]) -> tuple[list[str], list[str]]:
    hard = [t for t in toks if t not in _SOFT]
    soft = [t for t in toks if t in _SOFT]
    if not hard:              # a query made only of unit words: search them for real
        return soft, []
    return hard, soft


def _fts_expr(toks: list[str], op: str) -> str:
    parts = []
    for t in toks:
        safe = t.replace('"', "")
        if not safe:
            continue
        parts.append(f'"{safe}"*')
    return f" {op} ".join(parts)


def _rows(con: sqlite3.Connection, expr: str, schema: str, kind: str | None,
          module_id: int | None, limit: int, track: str | None = None) -> list[sqlite3.Row]:
    where = ""
    params: list = [expr]
    if kind:
        where += " AND f.kind = ?"
        params.append(kind)
    if module_id is not None:
        where += " AND f.module_id = ?"
        params.append(module_id)
    if track:
        where += " AND f.track = ?"
        params.append(track)
    params.append(limit)
    # FTS5 wants the bare table name (never schema-qualified, never an alias) on the left
    # of MATCH and inside bm25(), even when the bank is ATTACHed under a schema prefix.
    sql = f"""
        SELECT f.*, bm25(facts_fts, 8.0, 3.0, 1.0) AS bm
        FROM {schema}facts_fts
        JOIN {schema}facts f ON f.fid = facts_fts.fid
        WHERE facts_fts MATCH ?{where}
        ORDER BY bm
        LIMIT ?
    """
    return con.execute(sql, params).fetchall()


TRACKS = ("osha", "qaqc")
TRACK_LABEL = {None: "all tracks", "osha": "OSHA 30", "qaqc": "QA/QC"}
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def _topic(module_id) -> str:
    if not module_id:
        return ""
    if module_id >= 101:
        from ..content.qaqc import TOPICS as QAQC_TOPICS
        return QAQC_TOPICS.get(module_id, "")
    return TOPICS.get(module_id, "")


def _cjk_search(con: sqlite3.Connection, query: str, schema: str, kind: str | None,
                module_id: int | None, limit: int, track: str | None) -> list[dict]:
    """Chinese query (e.g. a 繁體中文 glossary name such as 上鎖掛籤): plain substring match on
    the stored Chinese name, subject and value. Every run of Chinese characters in the query
    must appear; an exact match on the Chinese name ranks first."""
    runs = _CJK.findall(query)
    where, params = [], []
    for run in runs:
        where.append("(coalesce(f.zh,'') || ' ' || f.subject || ' ' || f.value) LIKE ?")
        params.append(f"%{run}%")
    for col, val in (("f.kind", kind), ("f.module_id", module_id), ("f.track", track)):
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    rows = con.execute(
        f"SELECT f.* FROM {schema}facts f WHERE {' AND '.join(where)} LIMIT ?",
        (*params, limit * 3),
    ).fetchall()
    joined = "".join(runs)
    out = []
    for r in rows:
        d = dict(r)
        zh = d.get("zh") or ""
        d["score"] = 0.0 if zh == joined else (1.0 if joined in zh else 2.0)
        d["topic"] = _topic(d["module_id"])
        out.append(d)
    out.sort(key=lambda d: (d["score"], len(d.get("zh") or ""), d["subject"]))
    return out[:limit]


def search(con: sqlite3.Connection, query: str, *, kind: str | None = None,
           module_id: int | None = None, limit: int = 12, schema: str = "",
           track: str | None = "osha") -> list[dict]:
    """Ranked facts for a free-text query. Tries all-words-must-match first, then tops up
    with any-word matches. Returns plain dicts with a `score` (lower is better) and `topic`.

    `track`: 'osha' (the default, what every caller before the QA/QC track got), 'qaqc', or
    None for both. The Look Up screen and the CLI pass the reader's own choice (both, by
    default). A query containing Chinese characters searches the glossary's Chinese names."""
    if track is not None and track not in TRACKS:
        raise ValueError(f"unknown track {track!r}")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if _CJK.search(query):
        return _cjk_search(con, query, schema, kind, module_id, limit, track)
    toks = tokens(query)
    if not toks:
        return []

    hard, soft = split_hard_soft(toks)
    soft_rx = [re.compile(r"\b" + re.escape(t), re.I) for t in soft]
    soft_groups = {_group(_SOFT_UNIT[t]) for t in soft if t in _SOFT_UNIT}

    found: dict[str, dict] = {}
    for op in ("AND", "OR"):
        if len(found) >= limit:
            break
        expr = _fts_expr(hard, op)
        if not expr:
            break
        try:
            rows = _rows(con, expr, schema, kind, module_id, limit * 3, track)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                raise RuntimeError("fact base missing -- run: ./dashboard.sh build") from exc
            raise
        for r in rows:
            if r["fid"] in found:
                continue
            d = dict(r)
            unit_wanted = _group(d["unit"]) in soft_groups
            # A numeric fact in the unit the asker named is a likely answer even if it only
            # shares some of the words, so it skips the any-word penalty.
            or_penalty = 0.0 if (op == "AND" or unit_wanted) else 5.0
            d["score"] = float(r["bm"]) + _KIND_PENALTY.get(r["kind"], 0.0) + or_penalty
            hay = f"{d['subject']} {d['value']}"
            d["score"] -= 1.5 * sum(1 for rx in soft_rx if rx.search(hay))
            if unit_wanted:
                d["score"] -= 6.0
            d["topic"] = _topic(d["module_id"])
            found[r["fid"]] = d
    ranked = sorted(found.values(), key=lambda d: (d["score"], d["kind"], d["page"]))
    return ranked[:limit]


def is_qaqc(d: dict) -> bool:
    return d.get("track") == "qaqc"


def cite(d: dict) -> str:
    """Where a fact comes from: 'p.42' for the OSHA guide, the source label for QA/QC."""
    if is_qaqc(d):
        return f"source: {d.get('source_label') or ''}"
    return f"p.{d['page']}"


def one_line(d: dict, width: int = 100) -> str:
    """Compact single-line rendering used by the CLI --plain mode and the screen list."""
    label = KIND_LABEL.get(d["kind"], d["kind"].upper())
    head = d["subject"] if d["kind"] in ("term", "threshold", "deadline", "cfr", "sds") else d["topic"]
    if d.get("zh"):
        head = f"{head} {d['zh']}"
    if is_qaqc(d):
        label = f"QA/QC {label}"
    body = d["value"]
    text = f"[{label}] {head} -- {body}"
    if len(text) > width:
        text = text[: width - 3] + "..."
    return f"{text}  ({cite(d)})"


def has_facts(con: sqlite3.Connection, schema: str = "") -> bool:
    sql = "SELECT 1 FROM {s}sqlite_master WHERE type='table' AND name='facts'"
    return con.execute(sql.format(s=schema)).fetchone() is not None
