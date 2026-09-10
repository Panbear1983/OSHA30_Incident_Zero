"""Inspect: one ordered checklist per module, built at bank-build time from 'rule' facts.

Each item is one must/shall sentence the guide states, verbatim, in page order, so walking
a module's checklist is walking the guide's own requirements for that topic. Deterministic:
same fact base in, same checklist out. Nothing here touches progress.db -- ticks live there,
items live here.

Contract: build_and_insert(con, ctx) inserts into checklist_items on the given bank
connection and returns {'items': n, 'modules': m} (or {} if there were no rule facts).
"""
import hashlib

from .norm import norm_cf


def _cid(module_id: int, text: str) -> str:
    return hashlib.sha1(f"{module_id}|{norm_cf(text)}".encode("utf-8")).hexdigest()[:12]


def build_and_insert(con, ctx) -> dict:
    rows = con.execute(
        "SELECT rowid, fid, module_id, lesson_id, value, page, cfr FROM facts "
        "WHERE kind='rule' AND module_id IS NOT NULL ORDER BY module_id, page, rowid"
    ).fetchall()
    if not rows:
        return {}

    total = 0
    modules_with_items: set[int] = set()
    seq_by_module: dict[int, int] = {}
    seen: set[str] = set()
    for r in rows:
        text = r["value"]
        cid = _cid(r["module_id"], text)
        if cid in seen:            # near-identical sentence already listed for this module
            continue
        seen.add(cid)
        seq = seq_by_module.get(r["module_id"], 0) + 1
        seq_by_module[r["module_id"]] = seq
        con.execute(
            "INSERT INTO checklist_items (cid, module_id, lesson_id, seq, text, page, cfr, fid) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, r["module_id"], r["lesson_id"], seq, text, r["page"], r["cfr"], r["fid"]),
        )
        total += 1
        modules_with_items.add(r["module_id"])
    return {"items": total, "modules": len(modules_with_items)}
