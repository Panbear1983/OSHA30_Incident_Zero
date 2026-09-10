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
        rows = con.execute(
            "SELECT origin, category, COUNT(*) FROM questions GROUP BY origin, category ORDER BY origin, category"
        ).fetchall()
        total = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        print(f"  bank.db:     {total} questions")
        for r in rows:
            print(f"    {r['origin']:<13} {r['category']:<14} {r[2]}")
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
    from .ui.app import InspectorApp
    InspectorApp().run()
    return 0


def cmd_ai(argv: list[str]) -> int:
    print("AI scenario generation isn't built yet (Phase 5).")
    return 0


def cmd_reset(argv: list[str]) -> int:
    print("Profile reset isn't built yet (Phase 3).")
    return 0


COMMANDS = {"build": cmd_build, "status": cmd_status, "run": cmd_run, "ai": cmd_ai, "reset": cmd_reset}


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
