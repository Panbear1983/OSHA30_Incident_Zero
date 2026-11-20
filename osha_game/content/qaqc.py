"""The QA/QC track: a separate study track next to the OSHA 30 course.

Six modules follow the weeks of the QA/QC pre-start program (ids 101-106, so they can never
collide with OSHA modules 1-23). Everything the track shows lives in data/qaqc/*.json and is
written into bank.db by `build_and_insert()`:

  questions   data/qaqc/questions/*.json   seed quiz (program) + questions written from the
                                           cached source pages; track='qaqc'
  facts       glossary.json, numbers.json  English / Traditional Chinese glossary and the key
                                           numbers table, shown in Look Up
  checklists  checklists.json              five QA/QC checklists for Inspect (+ Word/PDF)

Grounding works like the OSHA build (validate.grounded): a generated question is accepted
only when its `quote` is literally present in the cached text of the source page it cites
(content/qaqc_sources.py). Ungrounded generated questions are REJECTED. The 29 seed
questions come from the program's own quizzes and are kept like the OSHA 'imported' cards:
grounding is checked and reported, but a miss is a warning, not a reject.

Every QA/QC question, fact and checklist item carries a non-empty source URL and label.

  ./dashboard.sh qaqc fetch     download the source pages into data/cache/qaqc_sources/
  ./dashboard.sh qaqc build     back up bank.db + progress.db, migrate the schema (additive
                                for OSHA rows; verified row for row), insert the track
  ./dashboard.sh qaqc status    counts per module
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .. import db as dbmod
from .. import paths
from . import qaqc_sources as srcmod
from .norm import loose, norm_cf
from .qid import make_qid
from .types import Question
from .validate import structural_check

TRACK = "qaqc"
DATA_DIR = paths.DATA / "qaqc"
QUESTIONS_DIR = DATA_DIR / "questions"
BACKUP_DIR = paths.DATA / "backups"          # git-ignored; never inside exports/
REPORT_PATH = paths.CACHE / "qaqc_report.json"

# id -> (program week, full title, short topic)
MODULES: dict[int, tuple[int, str, str]] = {
    101: (1, "QA/QC Fundamentals and Documentation", "QA/QC Fundamentals"),
    102: (2, "Copper Structured Cabling and CCTV", "Copper Cabling and CCTV"),
    103: (3, "Fiber Optics", "Fiber Optics"),
    104: (4, "Power Cable Pulling and Testing", "Power Cable Pulling"),
    105: (5, "Electrical Safety, FMCS and Tools", "Electrical Safety and FMCS"),
    106: (6, "Site Readiness: Cleanroom, Heat, Onboarding", "Site Readiness"),
}
TITLES = {mid: v[1] for mid, v in MODULES.items()}
TOPICS = {mid: v[2] for mid, v in MODULES.items()}
MIN_QUOTE = 15          # a grounding quote shorter than this proves nothing


def module_id(n: int) -> int:
    """Program week / file module number 1..6 -> stored module id 101..106."""
    mid = 100 + int(n)
    if mid not in MODULES:
        raise ValueError(f"unknown QA/QC module {n}")
    return mid


def is_qaqc_module(mid) -> bool:
    return mid is not None and 101 <= int(mid) <= 199


def module_label(mid: int) -> str:
    """'Q1'..'Q6' for QA/QC modules, 'M01'..'M23' for OSHA ones."""
    return f"Q{int(mid) - 100}" if is_qaqc_module(mid) else f"M{int(mid):02d}"


# -- data files ------------------------------------------------------------------------------

def load_questions() -> list[dict]:
    out: list[dict] = []
    for p in sorted(QUESTIONS_DIR.glob("*.json")):
        for i, e in enumerate(json.loads(p.read_text(encoding="utf-8"))):
            e = dict(e)
            e["_file"] = f"{p.name}#{i}"
            out.append(e)
    return out


def load_json(name: str) -> list[dict]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _source(key: str) -> srcmod.Source:
    if key not in srcmod.BY_KEY:
        raise ValueError(f"unknown QA/QC source key {key!r}")
    return srcmod.BY_KEY[key]


def _quote_ok(quote, key: str, texts: dict[str, str]) -> bool:
    return bool(quote) and len(quote) >= MIN_QUOTE and srcmod.grounded(quote, key, texts)


_ANCHOR_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "only", "must", "should", "into", "than",
    "then", "when", "what", "which", "your", "they", "them", "their", "there", "have", "been",
    "will", "would", "about", "after", "before", "under", "over", "each", "every", "other",
    "also", "such", "same", "does", "done", "never", "always", "unless", "yes", "not", "none",
    "it's", "don't", "can't", "isn't",
}


def _anchor_tokens(s: str) -> set[str]:
    text = loose(s).replace("-", " ")
    out = set(re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")))     # bare numbers: 260mm -> 260
    for t in re.findall(r"[a-z0-9][a-z0-9.,/%']*", text):
        t = t.strip(".,'")
        if not t or t in _ANCHOR_STOP:
            continue
        if any(ch.isdigit() for ch in t):
            out.add(t.replace(",", ""))
        elif len(t) >= 4:
            out.add(t[:-1] if t.endswith("s") and len(t) > 4 else t)
    return out


def answer_anchored(correct: str, quote: str) -> bool:
    """The second half of the grounding rule: the correct answer must share at least one
    number or content word with the quote that is on the source page, so the quote actually
    supports the answer rather than just being some sentence from the same page."""
    return bool(_anchor_tokens(correct) & _anchor_tokens(quote))


# -- build ------------------------------------------------------------------------------------

def build_questions(texts: dict[str, str]) -> tuple[list[tuple[Question, dict]], dict]:
    """Returns ([(Question, entry)...] accepted, report). Pure: no database access."""
    accepted: list[tuple[Question, dict]] = []
    rep = {"generated": 0, "seed": 0, "accepted": 0, "rejected": [], "seed_ungrounded": []}
    seen: set[str] = set()
    for e in load_questions():
        origin = e.get("origin")
        rep["seed" if origin == "seed" else "generated"] += 1
        src = _source(e["source"])
        grounded = _quote_ok(e.get("quote"), src.key, texts)
        q = Question(
            kind=e["kind"], category="qaqc_seed" if origin == "seed" else "qaqc",
            module_id=module_id(e["module"]), lesson_id=None,
            prompt=e["prompt"], correct=e["correct"], options=list(e["options"]),
            explanation=e.get("explanation"), cfr=None, page=None, source_doc="qaqc",
            source_quote=e.get("quote") if grounded else None,
            origin="imported" if origin == "seed" else "claude",
        )
        reason = structural_check(q)
        if reason is None and origin != "seed" and not grounded:
            reason = ("quote_missing_or_short" if not e.get("quote") or len(e["quote"]) < MIN_QUOTE
                      else "source_not_cached" if src.key not in texts
                      else "not_grounded_on_source")
        if reason is None and origin != "seed" and not answer_anchored(q.correct, e["quote"]):
            reason = "answer_not_supported_by_quote"
        if reason is None:
            qid = make_qid(q.kind, q.category, q.prompt, q.correct)
            if qid in seen:
                reason = "duplicate_in_batch"
            seen.add(qid)
        if reason:
            rep["rejected"].append({"where": e["_file"], "reason": reason, "prompt": e["prompt"][:90]})
            continue
        if origin == "seed" and not grounded:
            rep["seed_ungrounded"].append({"seed_no": e.get("seed_no"), "source": src.key,
                                           "prompt": e["prompt"][:90]})
        accepted.append((q, e))
        rep["accepted"] += 1
    return accepted, rep


def _fid(kind: str, subject: str, value: str) -> str:
    return hashlib.sha1(f"qaqc|{kind}|{norm_cf(subject)}|{norm_cf(value)}".encode("utf-8")).hexdigest()[:12]


def build_facts(texts: dict[str, str]) -> tuple[list[dict], dict]:
    """Glossary terms (kind 'term', with zh) and key numbers (kind 'threshold').
    A key number whose quote is not on its source is dropped (numbers must be exact); a
    glossary term is kept for its translation, with an empty quote, and reported."""
    rows: list[dict] = []
    rep = {"terms": 0, "terms_unverified": [], "numbers": 0, "numbers_rejected": []}
    for g in load_json("glossary.json"):
        src = _source(g["source"])
        ok = _quote_ok(g.get("quote"), src.key, texts)
        if not ok:
            rep["terms_unverified"].append(g["en"])
        rows.append({
            "fid": _fid("term", g["en"], g["def"]), "kind": "term", "subject": g["en"],
            "value": g["def"], "quote": g["quote"] if ok else "", "zh": g["zh"],
            "module_id": module_id(g["module"]), "number": None, "unit": None,
            "source_url": src.url, "source_label": src.label,
        })
        rep["terms"] += 1
    for n in load_json("numbers.json"):
        src = _source(n["source"])
        if not _quote_ok(n.get("quote"), src.key, texts):
            rep["numbers_rejected"].append(n["subject"])
            continue
        rows.append({
            "fid": _fid("threshold", n["subject"], n["value"]), "kind": "threshold",
            "subject": n["subject"], "value": n["value"], "quote": n["quote"], "zh": None,
            "module_id": module_id(n["module"]), "number": n.get("number"), "unit": n.get("unit"),
            "source_url": src.url, "source_label": src.label,
        })
        rep["numbers"] += 1
    return rows, rep


def checklist_cid(key: str, text: str) -> str:
    return hashlib.sha1(f"qaqc|{key}|{norm_cf(text)}".encode("utf-8")).hexdigest()[:12]


def build_checklists(texts: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    lists, items = [], []
    rep = {"lists": 0, "items": 0, "items_quote_verified": 0}
    for seq, cl in enumerate(load_json("checklists.json"), start=1):
        lists.append({"key": cl["key"], "module_id": module_id(cl["module"]), "seq": seq,
                      "title": cl["title"], "intro": cl["intro"]})
        rep["lists"] += 1
        n = 0
        for sec in cl["sections"]:
            for it in sec["items"]:
                n += 1
                src = _source(it["source"])
                ok = _quote_ok(it.get("quote"), src.key, texts)
                rep["items_quote_verified"] += int(ok)
                items.append({"cid": checklist_cid(cl["key"], it["text"]), "list_key": cl["key"],
                              "seq": n, "section": sec["name"], "text": it["text"],
                              "source_url": src.url, "source_label": src.label,
                              "quote": it["quote"] if ok else None})
                rep["items"] += 1
    return lists, items, rep


def build_and_insert(con: sqlite3.Connection, texts: dict[str, str] | None = None) -> dict:
    """(Re)write every QA/QC row on a bank connection whose schema is already current.
    Touches only QA/QC rows and the qaqc_* tables. Returns the build report."""
    texts = srcmod.loose_texts() if texts is None else texts
    accepted, qrep = build_questions(texts)
    facts, frep = build_facts(texts)
    lists, items, crep = build_checklists(texts)

    con.execute("DELETE FROM facts_fts WHERE fid IN (SELECT fid FROM facts WHERE track='qaqc')")
    con.execute("DELETE FROM facts WHERE track='qaqc'")
    con.execute("DELETE FROM questions WHERE track='qaqc'")
    con.execute("DELETE FROM qaqc_checklist_items")
    con.execute("DELETE FROM qaqc_checklists")
    con.execute("DELETE FROM qaqc_modules")

    for mid, (week, title, topic) in MODULES.items():
        con.execute("INSERT INTO qaqc_modules (id, week, title, topic) VALUES (?,?,?,?)",
                    (mid, week, title, topic))

    per_module: dict[int, int] = {mid: 0 for mid in MODULES}
    for q, e in accepted:
        src = _source(e["source"])
        qid = make_qid(q.kind, q.category, q.prompt, q.correct)
        con.execute(
            "INSERT INTO questions (qid, kind, category, module_id, lesson_id, prompt, correct, "
            " options, explanation, cfr, page, source_doc, source_quote, origin, track, "
            " source_url, source_label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, q.kind, q.category, q.module_id, None, q.prompt, q.correct,
             json.dumps(q.options), q.explanation, None, None, "qaqc", q.source_quote,
             q.origin, TRACK, src.url, src.label),
        )
        per_module[int(q.module_id or 0)] += 1

    for f in facts:
        con.execute(
            "INSERT INTO facts (fid, kind, subject, value, quote, page, module_id, lesson_id, cfr, "
            " number, unit, source_doc, track, source_url, source_label, zh) "
            "VALUES (?,?,?,?,?,0,?,NULL,NULL,?,?,'qaqc','qaqc',?,?,?)",
            (f["fid"], f["kind"], f["subject"], f["value"], f["quote"], f["module_id"],
             f["number"], f["unit"], f["source_url"], f["source_label"], f["zh"]),
        )
        fts_subject = f"{f['subject']} {f['zh']}" if f["zh"] else f["subject"]
        con.execute("INSERT INTO facts_fts (subject, value, quote, fid) VALUES (?,?,?,?)",
                    (fts_subject, f["value"], f["quote"], f["fid"]))

    for cl in lists:
        con.execute("INSERT INTO qaqc_checklists (key, module_id, seq, title, intro) VALUES (?,?,?,?,?)",
                    (cl["key"], cl["module_id"], cl["seq"], cl["title"], cl["intro"]))
    for it in items:
        con.execute(
            "INSERT INTO qaqc_checklist_items (cid, list_key, seq, section, text, source_url, "
            " source_label, quote) VALUES (?,?,?,?,?,?,?,?)",
            (it["cid"], it["list_key"], it["seq"], it["section"], it["text"],
             it["source_url"], it["source_label"], it["quote"]),
        )
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('qaqc_questions', ?)",
                (str(sum(per_module.values())),))
    return {
        "questions": qrep, "per_module": {module_label(m): n for m, n in per_module.items()},
        "facts": frep, "checklists": crep,
        "sources_cached": sorted(texts), "sources_missing": sorted(
            s.key for s in srcmod.SOURCES if s.key not in texts),
    }


# -- schema migration (existing bank.db -> track-aware schema) -------------------------------

_OSHA_COLS = {
    "questions": ["qid", "kind", "category", "module_id", "lesson_id", "prompt", "correct",
                  "options", "explanation", "cfr", "page", "source_doc", "source_quote", "origin"],
    "facts": ["fid", "kind", "subject", "value", "quote", "page", "module_id", "lesson_id",
              "cfr", "number", "unit", "source_doc"],
}


def _columns(con, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]


def needs_migration(con) -> bool:
    return "track" not in _columns(con, "questions") or "track" not in _columns(con, "facts") \
        or con.execute("SELECT 1 FROM sqlite_master WHERE name='qaqc_modules'").fetchone() is None


def table_ddl(name: str) -> str:
    """The CREATE TABLE statement for `name` as written in db.BANK_DDL."""
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {name}\((.*?)\);\n", dbmod.BANK_DDL, re.S)
    if not m:
        raise RuntimeError(f"no DDL for {name}")
    return f"CREATE TABLE {name}({m.group(1)});"


def osha_snapshot(con) -> dict[str, list]:
    """(row count, sha256) per OSHA table, over the original columns only, in key order.
    Used to prove the migration left every OSHA row exactly as it was."""
    track_q = " WHERE track='osha'" if "track" in _columns(con, "questions") else ""
    track_f = " WHERE track='osha'" if "track" in _columns(con, "facts") else ""
    queries = {
        "questions": f"SELECT {', '.join(_OSHA_COLS['questions'])} FROM questions{track_q} ORDER BY qid",
        "facts": f"SELECT {', '.join(_OSHA_COLS['facts'])} FROM facts{track_f} ORDER BY fid",
        "facts_fts": "SELECT fid, subject, value, quote FROM facts_fts WHERE fid IN "
                     f"(SELECT fid FROM facts{track_f}) ORDER BY fid",
        "modules": "SELECT * FROM modules ORDER BY id",
        "lessons": "SELECT * FROM lessons ORDER BY id",
        "checklist_items": "SELECT * FROM checklist_items ORDER BY cid",
        "scenarios": "SELECT * FROM scenarios ORDER BY sid",
    }
    out = {}
    for name, sql in queries.items():
        rows = [list(r) for r in con.execute(sql).fetchall()]
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()
        out[name] = [len(rows), digest]
    return out


def migrate_bank(con: sqlite3.Connection) -> list[str]:
    """Bring an existing bank.db to the track-aware schema. OSHA rows are copied column for
    column (new columns get track='osha' and NULL source fields). Idempotent. Returns the
    steps taken. Uses SQLite's documented create-copy-drop-rename procedure for the two
    tables whose CHECK constraints change."""
    steps: list[str] = []
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.execute("BEGIN")
        for table, index_sql in (
            ("questions", ["CREATE INDEX IF NOT EXISTS idx_q_module ON questions(module_id)",
                           "CREATE INDEX IF NOT EXISTS idx_q_cat ON questions(category)",
                           "CREATE INDEX IF NOT EXISTS idx_q_track ON questions(track)"]),
            ("facts", ["CREATE INDEX IF NOT EXISTS idx_f_kind ON facts(kind)",
                       "CREATE INDEX IF NOT EXISTS idx_f_module ON facts(module_id)",
                       "CREATE INDEX IF NOT EXISTS idx_f_track ON facts(track)"]),
        ):
            if "track" in _columns(con, table):
                continue
            cols = ", ".join(_OSHA_COLS[table])
            con.execute(table_ddl(table).replace(f"CREATE TABLE {table}(", f"CREATE TABLE {table}_new(", 1))
            con.execute(f"INSERT INTO {table}_new ({cols}, track) SELECT {cols}, 'osha' FROM {table}")
            before = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            after = con.execute(f"SELECT COUNT(*) FROM {table}_new").fetchone()[0]
            if before != after:
                raise RuntimeError(f"{table}: copied {after} of {before} rows")
            con.execute(f"DROP TABLE {table}")
            con.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
            for sql in index_sql:
                con.execute(sql)
            steps.append(f"{table}: rebuilt with track/source columns, {after} rows copied")
        for name in ("qaqc_modules", "qaqc_checklists", "qaqc_checklist_items"):
            if con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is None:
                con.execute(table_ddl(name).replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
                steps.append(f"{name}: created")
        con.execute("CREATE INDEX IF NOT EXISTS idx_qci_list ON qaqc_checklist_items(list_key, seq)")
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"foreign key check failed: {bad[:3]}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
    return steps


def backup(db_path: Path, label: str) -> Path | None:
    """Consistent copy (SQLite backup API, WAL-safe) into data/backups/. None if absent."""
    if not db_path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{label}-{stamp}.db"
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


# -- CLI ------------------------------------------------------------------------------------------

def _print_report(rep: dict) -> None:
    q = rep["questions"]
    print(f"questions: {q['accepted']} accepted ({q['seed']} seed, {q['generated']} generated), "
          f"{len(q['rejected'])} rejected")
    print("  per module: " + "  ".join(f"{k}={v}" for k, v in rep["per_module"].items()))
    for r in q["rejected"]:
        print(f"  REJECTED {r['where']}: {r['reason']} -- {r['prompt']}")
    if q["seed_ungrounded"]:
        print(f"  seeds kept but not found on their cited page ({len(q['seed_ungrounded'])}): "
              + ", ".join(f"#{s['seed_no']}" for s in q["seed_ungrounded"]))
    f = rep["facts"]
    print(f"look up: {f['terms']} glossary terms ({len(f['terms_unverified'])} without a verified "
          f"source quote), {f['numbers']} key numbers ({len(f['numbers_rejected'])} rejected)")
    if f["numbers_rejected"]:
        print("  REJECTED numbers: " + ", ".join(f["numbers_rejected"]))
    c = rep["checklists"]
    print(f"inspect: {c['lists']} checklists, {c['items']} items "
          f"({c['items_quote_verified']} with a verified source quote)")
    if rep["sources_missing"]:
        print("sources not cached: " + ", ".join(rep["sources_missing"]))


def cmd_build(argv: list[str]) -> int:
    if not paths.BANK_DB.exists():
        print("No bank.db yet -- run './dashboard.sh build' first.")
        return 1
    if not srcmod.have_cache():
        print("No QA/QC source cache -- run './dashboard.sh qaqc fetch' first.")
        return 1
    b1 = backup(paths.BANK_DB, "bank")
    b2 = backup(paths.PROGRESS_DB, "progress")
    print(f"backed up bank.db -> {b1}")
    if b2:
        print(f"backed up progress.db -> {b2}")
    con = dbmod.bank_connect(paths.BANK_DB)
    try:
        before = osha_snapshot(con)
        steps = migrate_bank(con) if needs_migration(con) else []
        for s in steps:
            print(f"migrated {s}")
        con.execute("BEGIN")
        rep = build_and_insert(con)
        con.execute("COMMIT")
        after = osha_snapshot(con)
        if before != after:
            changed = [k for k in before if before[k] != after.get(k)]
            print(f"OSHA ROWS CHANGED in {changed} -- restore from {b1}")
            return 3
        print("OSHA rows verified identical before/after: "
              + ", ".join(f"{k}={v[0]}" for k, v in after.items()))
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()
    rep["osha_snapshot"] = after
    rep["migration_steps"] = steps
    paths.ensure_dirs()
    REPORT_PATH.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    _print_report(rep)
    print(f"report: {REPORT_PATH}")
    return 0


def cmd_status(argv: list[str]) -> int:
    con = dbmod.bank_connect(paths.BANK_DB)
    try:
        if needs_migration(con):
            print("bank.db has no QA/QC track yet -- run './dashboard.sh qaqc build'.")
            return 1
        for r in con.execute(
            "SELECT m.id, m.title, COUNT(q.qid) FROM qaqc_modules m LEFT JOIN questions q "
            "ON q.module_id = m.id AND q.track='qaqc' GROUP BY m.id ORDER BY m.id"
        ).fetchall():
            print(f"  {module_label(r[0])}  {r[1]:<46} {r[2]:>4} questions")
        nf = con.execute("SELECT kind, COUNT(*) FROM facts WHERE track='qaqc' GROUP BY kind").fetchall()
        print("  facts: " + "  ".join(f"{k}={n}" for k, n in nf))
        for r in con.execute("SELECT c.key, c.title, COUNT(i.cid) FROM qaqc_checklists c "
                             "JOIN qaqc_checklist_items i ON i.list_key=c.key GROUP BY c.key ORDER BY c.seq"):
            print(f"  checklist {r[0]:<16} {r[1]:<46} {r[2]:>3} items")
    finally:
        con.close()
    return 0


def main(argv: list[str]) -> int:
    sub = argv[0] if argv else "status"
    if sub == "fetch":
        status = srcmod.fetch(force="--force" in argv)
        ok = sum(1 for v in status.values() if not v.startswith("error"))
        print(f"{ok} of {len(status)} sources cached in {srcmod.CACHE_DIR}")
        return 0
    if sub == "build":
        return cmd_build(argv[1:])
    if sub == "status":
        return cmd_status(argv[1:])
    print("usage: ./dashboard.sh qaqc [fetch [--force] | build | status]")
    return 2
