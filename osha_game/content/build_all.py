"""Orchestrates a full bank rebuild: modules/lessons rows -> all builders -> validate -> atomic swap.

This is the one place that owns write access to bank.db (well, bank.db.new, atomically
swapped in at the end) — no builder module ever opens a database connection itself.
"""
import json
from . import build_mc, build_blank, importer, validate
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
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('modules', ?)", (str(len(ctx.modules)),))
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('lessons', ?)", (str(len(ctx.lessons)),))
    con.commit()
    con.close()

    tmp_path.replace(paths.BANK_DB)

    generated_counts = {k: len(v) for k, v in groups.items()}
    paths.BUILD_REPORT.write_text(json.dumps({
        "generated_counts": generated_counts,
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
    console.print(f"wrote {paths.BANK_DB}")
