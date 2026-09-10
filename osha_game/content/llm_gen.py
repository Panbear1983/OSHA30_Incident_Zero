"""Optional richer interview scenarios written by the LOCAL Ollama model at build time.

    ./dashboard.sh ai [--module N] [--lesson N] [--limit N] [--force] [--model TAG]

The model writes the QUESTION only (a 4-6 sentence workplace narrative). The answer is
always scenarios.answer_for_lesson() -- the guide's own words with pages. Every narrative
passes a grounding verifier before it is kept: it must name at least two of the supplied
facts verbatim and may not introduce any number+unit or CFR cite that was not supplied.
Accepted narratives go to data/ai_scenarios.json; `./dashboard.sh build` merges them.

The dashboard never needs Ollama running. If it is unreachable this prints one line and
exits 1. The `agy` (Gemini) backend is deliberately not used here.
"""
import json
import re
import sys
import urllib.error
import urllib.request

from . import mine
from . import scenarios as scmod
from .norm import norm_cf, normalize
from .. import config, db, paths

DEFAULT_MODEL = "qwen3:8b"
MIN_LEN, MAX_LEN = 200, 1200
AI_SCENARIOS = paths.DATA / "ai_scenarios.json"


# --- prompt --------------------------------------------------------------------------------

def _fact_lines(f: dict) -> tuple[list[str], list[str], list[str]]:
    """(bullet lines for the prompt, subjects the output must reuse, allowed cfr cites)."""
    lines, subjects, cites = [], [], []
    for t in f["terms"]:
        lines.append(f"- TERM {t['subject']}: {t['value'][:160]}")
        subjects.append(t["subject"])
    for n in f["numbers"]:
        lines.append(f"- NUMBER {n['subject']}: {n['value'][:200]}")
        subjects.append(n["subject"])
        if n["cfr"]:
            cites.append(n["cfr"])
    for s in f["standards"]:
        lines.append(f"- STANDARD {s['subject']}: {s['value'][:200]}")
        subjects.append(s["subject"])
        cites.append(s["cfr"])
    for r in f["rules"]:
        lines.append(f"- RULE: {r['value'][:220]}")
        if r["cfr"]:
            cites.append(r["cfr"])
    return lines, subjects, cites


def build_prompt(topic: str, lesson_label: str, fact_lines: list[str]) -> str:
    return (
        "You write realistic workplace-safety interview scenarios for an OSHA 30 General "
        "Industry candidate.\n"
        f"Topic: {topic} -- {lesson_label}\n"
        "Facts from the study guide (the ONLY facts you may draw on):\n"
        + "\n".join(fact_lines) +
        "\n\nWrite ONE scenario of 4 to 6 sentences, plain English, second person "
        "(\"you are ...\"). Describe ONLY what a site safety lead sees, measures, hears, or is "
        "told during a walkthrough: conditions, readings, labels, what workers say. "
        "Use at least two of the listed terms or numbers word for word as things observed "
        "(a measurement you take, a label you read, a word someone uses). "
        "Do NOT state any rule, requirement, deadline, or standard, and do NOT say whether "
        "anything is correct, compliant, required, or a violation -- the candidate must work "
        "that out. Never use the words: required, must, should, according to, as per, "
        "compliant, violation. Do not invent any numbers, measurements, or standard numbers "
        "that are not listed above. Do not give the answer. End with exactly: "
        "\"What applies here, and what do you do first, second, and third?\" "
        "Output only the scenario text."
    )


# A narrative that asserts rules is where a small local model goes wrong ("reported within
# 24 hours as required for a minor injury"), so any assertion vocabulary is rejected outright.
_ASSERTION_WORDS = re.compile(
    r"\b(required|requires|must|should|according to|as per|compliant|compliance|violation|"
    r"in accordance|mandated|mandatory|permitted|prohibited)\b", re.I)


# --- grounding -------------------------------------------------------------------------------

def verify(text: str, subjects: list[str], allowed_cites: list[str]) -> tuple[bool, str]:
    """Accept only a narrative that reuses the supplied facts and invents nothing checkable."""
    text = normalize(text)
    if not (MIN_LEN <= len(text) <= MAX_LEN):
        return False, f"length {len(text)} outside {MIN_LEN}-{MAX_LEN}"
    m_assert = _ASSERTION_WORDS.search(text)
    if m_assert:
        return False, f"asserts a rule ({m_assert.group(1)!r}); scenarios may only describe observations"
    low = norm_cf(text)
    hits = [s for s in subjects if norm_cf(s) in low]
    if len(hits) < 2:
        return False, f"only {len(hits)} supplied fact(s) named verbatim (need 2)"
    allowed_cf = {c.casefold() for c in allowed_cites}
    allowed_base = {mine.cfr_base(c).casefold() for c in allowed_cites}
    for m in mine.CFR.finditer(text):
        cite = m.group(1).casefold()
        if cite not in allowed_cf and mine.cfr_base(cite) not in allowed_base:
            return False, f"invented standard {m.group(1)}"
    allowed_nums = {norm_cf(s) for s in subjects}
    for m in mine.NUMUNIT.finditer(text):
        fam = mine.UNIT_FAMILY.get(m.group(2).lower().rstrip("."))
        if fam is None:
            continue
        span = norm_cf(m.group(0))
        value = mine.num_value(m.group(1))
        ok = any(
            span == a or (norm_cf(mine.fmt_num(value)) in a and fam in _family_of(a))
            for a in allowed_nums
        )
        if not ok:
            return False, f"invented number {m.group(0)!r}"
    return True, "ok"


def _family_of(subject_cf: str) -> set[str]:
    fams = set()
    for m in mine.NUMUNIT.finditer(subject_cf):
        fam = mine.UNIT_FAMILY.get(m.group(2).lower().rstrip("."))
        if fam:
            fams.add(fam)
    return fams


# --- ollama ----------------------------------------------------------------------------------

def _post(url: str, payload: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def reachable(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3):
            return True
    except Exception:
        return False


def generate(base_url: str, model: str, prompt: str, temperature: float) -> str:
    payload = {
        "model": model, "prompt": prompt, "stream": False, "think": False,
        "options": {"temperature": temperature, "num_predict": 450, "num_ctx": 8192},
    }
    try:
        out = _post(f"{base_url}/api/generate", payload)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        payload.pop("think", None)                    # older server: no `think` key
        payload["prompt"] = "/no_think\n" + prompt
        out = _post(f"{base_url}/api/generate", payload)
    text = out.get("response", "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)   # belt and braces
    return text.strip().strip('"').strip()


# --- driver ------------------------------------------------------------------------------------

def _parse(argv: list[str]) -> dict:
    opts = {"module": None, "lesson": None, "limit": None, "force": False, "model": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--force":
            opts["force"] = True; i += 1; continue
        if a in ("--module", "--lesson", "--limit", "--model") and i + 1 < len(argv):
            key = a[2:]
            opts[key] = argv[i + 1] if key == "model" else int(argv[i + 1])
            i += 2; continue
        if a in ("-h", "--help"):
            print(__doc__); raise SystemExit(0)
        print(f"unknown argument: {a}", file=sys.stderr); raise SystemExit(2)
    return opts


def _load_existing() -> list[dict]:
    if not AI_SCENARIOS.exists():
        return []
    try:
        return json.loads(AI_SCENARIOS.read_text())
    except json.JSONDecodeError:
        return []


def main(argv: list[str]) -> int:
    opts = _parse(argv)
    cfg = config.load()["ollama"]
    base_url = cfg["url"].rstrip("/")
    model = opts["model"] or (DEFAULT_MODEL if cfg["model"] == "auto" else cfg["model"])
    if not paths.BANK_DB.exists():
        print("No bank yet -- run './dashboard.sh build' first.")
        return 1
    if not reachable(base_url):
        print(f"Ollama is not reachable at {base_url}; the dashboard works without it, so nothing to do.")
        return 1

    con = db.bank_connect(paths.BANK_DB)
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='facts'").fetchone():
        print("This bank predates the fact base -- run './dashboard.sh build' first.")
        return 1

    where, params = [], []
    if opts["module"] is not None:
        where.append("l.module_id=?"); params.append(opts["module"])
    if opts["lesson"] is not None:
        where.append("l.id=?"); params.append(opts["lesson"])
    sql = ("SELECT l.id, l.module_id, l.label, m.topic FROM lessons l JOIN modules m ON m.id=l.module_id"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY l.id")
    lessons = con.execute(sql, params).fetchall()
    if opts["limit"]:
        lessons = lessons[: opts["limit"]]

    existing = _load_existing()
    have = {d["lesson_id"] for d in existing if d.get("origin") == "ollama"}
    accepted = skipped = 0
    for les in lessons:
        if les["id"] in have and not opts["force"]:
            print(f"  lesson {les['id']:>2} ({les['topic']}): already has an AI scenario, skipping (use --force)")
            continue
        f = scmod.facts_for_prompt(con, les["id"])
        lines, subjects, cites = _fact_lines(f)
        if len(subjects) < 2:
            print(f"  lesson {les['id']:>2} ({les['topic']}): fewer than 2 namable facts, skipping")
            skipped += 1
            continue
        prompt = build_prompt(les["topic"], les["label"], lines)
        outcome = None
        for attempt in (1, 2):
            text = generate(base_url, model, prompt, float(cfg.get("temperature", 0.7)))
            ok, why = verify(text, subjects, cites)
            if ok:
                outcome = text
                break
            print(f"  lesson {les['id']:>2} ({les['topic']}): attempt {attempt} rejected -- {why}")
        if outcome is None:
            skipped += 1
            continue
        sc = {
            "sid": scmod.make_sid("ollama", les["id"], outcome),
            "module_id": les["module_id"], "lesson_id": les["id"],
            "title": f"{les['topic']}: {les['label']}",
            "prompt": outcome,
            "answer_json": json.dumps(scmod.answer_for_lesson(con, les["id"])),
            "origin": "ollama", "model": model,
            "grounding": [s for s in subjects if norm_cf(s) in norm_cf(outcome)],
        }
        existing = [d for d in existing if not (d.get("lesson_id") == les["id"] and d.get("origin") == "ollama")]
        existing.append(sc)
        AI_SCENARIOS.write_text(json.dumps(existing, indent=1))
        accepted += 1
        print(f"  lesson {les['id']:>2} ({les['topic']}): accepted, names {len(sc['grounding'])} facts")

    print(f"done: {accepted} accepted, {skipped} skipped, {len(existing)} total in {AI_SCENARIOS.name}")
    if accepted:
        print("run './dashboard.sh build' to merge them into the bank.")
    return 0
