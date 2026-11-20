"""CLI dispatch. Always invoked as: venv/bin/python -m osha_game <cmd> [args...]"""
import sys


def cmd_build(argv: list[str]) -> int:
    from .content.build_all import rebuild, print_report
    report, generated_counts = rebuild()
    print_report(report, generated_counts)
    return 0


def cmd_status(argv: list[str]) -> int:
    import urllib.request
    from . import paths, db

    print("INCIDENT ZERO -- status")
    print(f"  python:      {sys.version.split()[0]}")
    print(f"  root:        {paths.ROOT}")
    print(f"  guide pdf:   {'present' if paths.GUIDE_PDF.exists() else 'MISSING'}")
    print(f"  sds pdf:     {'present' if paths.SDS_PDF.exists() else 'MISSING'}")

    if paths.BANK_DB.exists():
        con = db.bank_connect(paths.BANK_DB)
        has_track = "track" in {r[1] for r in con.execute("PRAGMA table_info(questions)")}
        where = " WHERE track='osha'" if has_track else ""
        rows = con.execute(
            f"SELECT origin, category, COUNT(*) FROM questions{where} "
            "GROUP BY origin, category ORDER BY origin, category"
        ).fetchall()
        total = con.execute(f"SELECT COUNT(*) FROM questions{where}").fetchone()[0]
        print(f"  bank.db:     {total} OSHA questions")
        for r in rows:
            print(f"    {r['origin']:<13} {r['category']:<14} {r[2]}")
        if has_track:
            nq = con.execute("SELECT COUNT(*) FROM questions WHERE track='qaqc'").fetchone()[0]
            print(f"  qa/qc track: {nq} questions -- details: ./dashboard.sh qaqc status")
        else:
            print("  qa/qc track: not in this bank -- run: ./dashboard.sh qaqc build")
        has_facts = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'").fetchone()
        if has_facts:
            frows = con.execute("SELECT kind, COUNT(*) FROM facts GROUP BY kind ORDER BY kind").fetchall()
            ftotal = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            print(f"  facts:       {ftotal}  " + "  ".join(f"{r[0]}={r[1]}" for r in frows))
        else:
            print("  facts:       none -- bank predates the fact base, run: ./dashboard.sh build")
        con.close()
    else:
        print("  bank.db:     not built yet -- run: ./dashboard.sh build")

    if paths.PROGRESS_DB.exists():
        con = db.game_connect()
        profiles = con.execute(
            "SELECT name, days_without_incident, best_streak FROM profiles ORDER BY last_seen_at DESC"
        ).fetchall()
        print(f"  profiles:    {len(profiles)}")
        for p in profiles:
            print(f"    {p['name']:<20} streak={p['days_without_incident']} best={p['best_streak']}")
        con.close()
    else:
        print("  profiles:    none yet")

    from . import config as cfgmod
    ollama_url = cfgmod.load()["ollama"]["url"]
    try:
        with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=2) as resp:
            import json
            names = [m["name"] for m in json.loads(resp.read())["models"]]
            print(f"  ollama:      reachable at {ollama_url}, {len(names)} models ({', '.join(names[:5])})")
    except Exception as exc:
        print(f"  ollama:      not reachable at {ollama_url} ({exc.__class__.__name__})")

    import shutil
    print(f"  agy cli:     {'found at ' + shutil.which('agy') if shutil.which('agy') else 'not on PATH'}")
    return 0


def cmd_run(argv: list[str]) -> int:
    from . import paths
    if not paths.BANK_DB.exists():
        print("No question bank yet -- run './dashboard.sh build' first.")
        return 1
    from . import db
    from .content import qaqc
    con = db.bank_connect(paths.BANK_DB)
    try:
        stale = qaqc.needs_migration(con)
    finally:
        con.close()
    if stale:
        print("This bank.db predates the QA/QC track -- run './dashboard.sh qaqc build' once "
              "(it backs up bank.db and progress.db first).")
        return 1
    from .ui.app import InspectorApp
    InspectorApp().run()
    return 0


def cmd_qaqc(argv: list[str]) -> int:
    """./dashboard.sh qaqc [fetch | build | status]  -- the separate QA/QC track."""
    from .content import qaqc
    return qaqc.main(argv)


def cmd_lookup(argv: list[str]) -> int:
    """./dashboard.sh lookup [--kind K] [--module N] [--track osha|qaqc|all] [--limit N] [--plain] words...
    Searches both tracks (OSHA 30 and QA/QC) unless --track narrows it. Chinese works too:
    ./dashboard.sh lookup 上鎖掛籤"""
    from . import paths, db
    from .lookup import search as srch

    kind = module_id = None
    track: str | None = None
    limit = 10
    plain = False
    words: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--kind", "-k") and i + 1 < len(argv):
            kind = argv[i + 1]; i += 2; continue
        if a in ("--module", "-m") and i + 1 < len(argv):
            module_id = int(argv[i + 1]); i += 2; continue
        if a in ("--track", "-t") and i + 1 < len(argv):
            track = None if argv[i + 1] == "all" else argv[i + 1]; i += 2; continue
        if a in ("--limit", "-n") and i + 1 < len(argv):
            limit = int(argv[i + 1]); i += 2; continue
        if a == "--plain":
            plain = True; i += 1; continue
        if a in ("-h", "--help"):
            print(cmd_lookup.__doc__); print("kinds:", ", ".join(srch.KINDS)); return 0
        words.append(a); i += 1
    query = " ".join(words).strip()
    if not query:
        print('usage: ./dashboard.sh lookup "guardrail height"   (add --plain for one line per hit)')
        return 2
    if not paths.BANK_DB.exists():
        print("No fact base yet -- run './dashboard.sh build' first.")
        return 1
    con = db.bank_connect(paths.BANK_DB)
    if not srch.has_facts(con):
        print("This bank predates the fact base -- run './dashboard.sh build' to add it.")
        return 1
    try:
        hits = srch.search(con, query, kind=kind, module_id=module_id, limit=limit, track=track)
    except ValueError as exc:
        print(exc); return 2
    if not hits:
        print(f"no facts match {query!r}")
        return 1
    if plain or not sys.stdout.isatty():
        for d in hits:
            print(srch.one_line(d, width=140))
        return 0

    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
    console.print(f"[bold]{len(hits)} facts for[/bold] [cyan]{query}[/cyan]")
    for d in hits:
        label = srch.KIND_LABEL.get(d["kind"], d["kind"].upper())
        if srch.is_qaqc(d):
            label = f"QA/QC {label}"
        t = Text()
        t.append(f"{label}  ", style="bold yellow")
        t.append(d["subject"], style="bold")
        if d.get("zh"):
            t.append(f"  {d['zh']}", style="bold cyan")
        t.append("\n")
        t.append(d["value"])
        meta = srch.cite(d)
        if d["cfr"]:
            meta += f"   29 CFR {d['cfr']}"
        if d["topic"]:
            from .content.qaqc import module_label
            meta += f"   {module_label(d['module_id'])} {d['topic']}"
        if srch.is_qaqc(d) and d.get("source_url"):
            meta += f"\n{d['source_url']}"
        t.append("\n" + meta, style="dim")
        console.print(Panel(t, border_style="blue", padding=(0, 1)))
    return 0


def cmd_ai(argv: list[str]) -> int:
    """./dashboard.sh ai [--module N] [--force]  -- optional Ollama-written interview
    scenarios (build-time only; the dashboard never needs Ollama running to play)."""
    from .content import llm_gen
    return llm_gen.main(argv)


def cmd_export(argv: list[str]) -> int:
    """./dashboard.sh export [--module N | --all] [--no-pdf]  -- write Inspect checklists
    as Word (+ PDF via LibreOffice when available) into exports/."""
    from .export import checklist as export_checklist
    return export_checklist.main(argv)


def cmd_reset(argv: list[str]) -> int:
    print("Profile reset isn't built yet (Phase 3).")
    return 0


COMMANDS = {
    "build": cmd_build, "status": cmd_status, "run": cmd_run, "ai": cmd_ai,
    "reset": cmd_reset, "lookup": cmd_lookup, "export": cmd_export, "qaqc": cmd_qaqc,
}


def main() -> int:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "run"
    handler = COMMANDS.get(cmd)
    if handler is None:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return handler(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
