"""Orchestrates a full bank rebuild: modules/lessons rows -> all builders -> validate -> atomic swap.

This is the one place that owns write access to bank.db (well, bank.db.new, atomically
swapped in at the end) — no builder module ever opens a database connection itself.
"""
import json
from . import build_mc, build_blank, importer, validate, facts as factsmod
from . import checklist as checklistmod, scenarios as scenariosmod
from .context import build_context
from .. import db as dbmod
from .. import paths


def _insert_modules_lessons(con, ctx) -> None:
    for mod in ctx.modules:
        con.execute(
            "INSERT OR REPLACE INTO modules (id, title, topic, page_start, page_end) "
            "VALUES (?,?,?,?,?)",
            (mod.id, mod.title, mod.topic, mod.page_start, mod.page_end),
        )
    for les in ctx.lessons:
        con.execute(
            "INSERT OR REPLACE INTO lessons (id, module_id, label, page_start, page_end) "
            "VALUES (?,?,?,?,?)",
            (les.id, les.module_id, les.label, les.page_start, les.page_end),
        )


def insert_facts(con, all_facts) -> dict:
    """Grounding-checked insert of the fact base: a fact whose quote is not literally on the
    page it cites is dropped, exactly like a question would be. Returns counts per kind
    plus 'rejected'."""
    from .norm import loose
    page_cache = validate._page_text_cache()
    counts: dict[str, int] = {"rejected": 0}
    seen: set[str] = set()
    for f in all_facts:
        page_text = page_cache.get((f.source_doc, f.page), "")
        needle = loose(f.quote)[:400]
        if not page_text or needle not in page_text:
            counts["rejected"] += 1
            continue
        fid = f.fid
        if fid in seen:
            counts["rejected"] += 1
            continue
        seen.add(fid)
        con.execute(
            "INSERT INTO facts (fid, kind, subject, value, quote, page, module_id, lesson_id, "
            " cfr, number, unit, source_doc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, f.kind, f.subject, f.value, f.quote, f.page, f.module_id, f.lesson_id,
             f.cfr, f.number, f.unit, f.source_doc),
        )
        con.execute(
            "INSERT INTO facts_fts (subject, value, quote, fid) VALUES (?,?,?,?)",
            (f.subject, f.value, f.quote, fid),
        )
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return counts


def rebuild():
    """Returns (report, generated_counts). Writes data/bank.db (atomic replace) and
    data/cache/build_report.json."""
    paths.ensure_dirs()
    ctx = build_context(force=True)

    tmp_path = paths.BANK_DB.parent / (paths.BANK_DB.name + ".new")
    if tmp_path.exists():
        tmp_path.unlink()
    con = dbmod.bank_connect(tmp_path, create=True)
    _insert_modules_lessons(con, ctx)

    groups = {
        "build_mc": build_mc.build(ctx),
        "build_blank": build_blank.build(ctx),
        "importer": importer.build(ctx),
    }
    all_qs = [q for qs in groups.values() for q in qs]

    report = validate.validate_all(con, all_qs, insert=True)
    fact_counts = insert_facts(con, factsmod.build(ctx))
    derived_counts = {}
    derived_counts.update(checklistmod.build_and_insert(con, ctx))
    derived_counts.update(scenariosmod.build_and_insert(con, ctx))
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('modules', ?)", (str(len(ctx.modules)),))
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('lessons', ?)", (str(len(ctx.lessons)),))
    con.commit()
    con.close()

    tmp_path.replace(paths.BANK_DB)

    generated_counts = {k: len(v) for k, v in groups.items()}
    report.facts = fact_counts
    report.derived = derived_counts
    paths.BUILD_REPORT.write_text(json.dumps({
        "generated_counts": generated_counts,
        "facts": fact_counts,
        "derived": derived_counts,
        "accepted": report.accepted,
        "rejected": report.rejected,
        "warnings": report.warnings,
        "by_category": report.by_category,
        "reasons": report.reasons,
    }, indent=2))
    return report, generated_counts


def print_report(report, generated_counts) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="INCIDENT ZERO -- bank build report")
    table.add_column("category")
    table.add_column("accepted", justify="right")
    for cat, n in sorted(report.by_category.items()):
        table.add_row(cat, str(n))
    console.print(table)
    console.print(
        f"generated {sum(generated_counts.values())}  "
        f"accepted [green]{report.accepted}[/green]  "
        f"rejected [red]{report.rejected}[/red]  "
        f"warnings [yellow]{report.warnings}[/yellow]"
    )
    if report.reasons:
        console.print("reject reasons:", dict(sorted(report.reasons.items(), key=lambda x: -x[1])))
    facts = getattr(report, "facts", None)
    if facts:
        shown = {k: v for k, v in facts.items() if k != "rejected"}
        console.print(f"facts: {sum(shown.values())} accepted {dict(sorted(shown.items()))}  "
                      f"rejected [red]{facts.get('rejected', 0)}[/red]")
    derived = getattr(report, "derived", None)
    if derived:
        console.print(f"derived: {dict(sorted(derived.items()))}")
    console.print(f"wrote {paths.BANK_DB}")
