"""Interview: one scenario per lesson with a model answer assembled from facts, built at
bank-build time from the `facts` table (never from the PDF directly, never from an LLM).

Contract used by build_all: build_and_insert(con, ctx) inserts into `scenarios` on the
given bank connection and returns {'scenarios': n, 'ai_scenarios': m}.

Two origins share the table:
  deterministic -- one per lesson, templated prompt, built here. No randomness.
  ollama        -- optional richer narratives written at build time by content/llm_gen.py
                   and stored in data/ai_scenarios.json; merged as-is (INSERT OR IGNORE).
Both carry the same answer_json shape, and the answer is ALWAYS the deterministic one
(answer_for_lesson) -- the model only ever writes the question, never the answer.
"""
import hashlib
import json

from .norm import norm_cf
from .. import paths

ANSWER_KEYS = ("standards", "numbers", "terms", "rules", "steps")
_MAX_PER_LIST = 4
_MIN_LESSON_FACTS = 3

_PROMPT_TEMPLATE = (
    "You are the site safety lead at a general-industry plant. During a walkthrough of the "
    "{topic} area ({lesson}) you find {situation}. A supervisor asks you what the rules are "
    "and what happens next. Talk through: which OSHA standard applies, what the specific "
    "numbers or conditions are, and what you would do first, second, and third."
)


def make_sid(origin: str, lesson_id: int, text: str) -> str:
    return hashlib.sha1(f"{origin}|{lesson_id}|{norm_cf(text)}".encode("utf-8")).hexdigest()[:12]


# --- fact lookups ---------------------------------------------------------------------------

def _lesson_row(con, lesson_id: int):
    return con.execute(
        "SELECT l.id, l.module_id, l.label, m.topic FROM lessons l JOIN modules m ON m.id=l.module_id "
        "WHERE l.id=?", (lesson_id,)
    ).fetchone()


def _facts(con, kinds: tuple, lesson_id: int | None, module_id: int, limit: int) -> list:
    """Facts of the given kinds for a lesson, falling back to the whole module when the
    lesson alone has fewer than _MIN_LESSON_FACTS of them. Page order, deterministic."""
    marks = ",".join("?" * len(kinds))
    rows = []
    if lesson_id is not None:
        rows = con.execute(
            f"SELECT * FROM facts WHERE kind IN ({marks}) AND lesson_id=? ORDER BY page, fid",
            (*kinds, lesson_id),
        ).fetchall()
    if len(rows) < _MIN_LESSON_FACTS:
        rows = con.execute(
            f"SELECT * FROM facts WHERE kind IN ({marks}) AND module_id=? ORDER BY page, fid",
            (*kinds, module_id),
        ).fetchall()
    return rows[:limit]


def _lesson_terms(con, lesson_id: int, module_id: int, limit: int) -> list:
    """Glossary terms are module-scoped (no lesson_id). Prefer the ones this lesson's own
    sentences actually use; top up from the module's terms in page order."""
    module_terms = con.execute(
        "SELECT * FROM facts WHERE kind='term' AND module_id=? ORDER BY page, fid", (module_id,)
    ).fetchall()
    lesson_text = " ".join(
        r["value"] for r in con.execute(
            "SELECT value FROM facts WHERE lesson_id=? AND kind IN ('rule','threshold','deadline','cfr')",
            (lesson_id,),
        ).fetchall()
    ).casefold()
    import re
    used = [t for t in module_terms
            if re.search(r"\b" + re.escape(t["subject"].casefold()) + r"\b", lesson_text)]
    rest = [t for t in module_terms if t not in used]
    return (used + rest)[:limit]


def _steps(rules: list) -> list[str]:
    steps = ["Stop the task and control the hazard before anyone continues working."]
    if rules:
        steps.append(f"Verify the requirement: {rules[0]['value']} (p. {rules[0]['page']})")
    else:
        steps.append("Verify the requirement against the OSHA standard and the written program.")
    steps.append("Document what you found, correct it, and follow up with training or a program update.")
    return steps


def answer_for_lesson(con, lesson_id: int) -> dict:
    """The model answer for a lesson: verbatim facts with pages, at most 4 per section.
    Shared by the deterministic builder and the Ollama generator so every scenario, whatever
    wrote its question, is answered by the guide's own words."""
    les = _lesson_row(con, lesson_id)
    if les is None:
        raise ValueError(f"unknown lesson {lesson_id}")
    module_id = les["module_id"]
    standards = _facts(con, ("cfr",), lesson_id, module_id, _MAX_PER_LIST)
    numbers = _facts(con, ("threshold", "deadline"), lesson_id, module_id, _MAX_PER_LIST)
    terms = _lesson_terms(con, lesson_id, module_id, _MAX_PER_LIST)
    rules = _facts(con, ("rule",), lesson_id, module_id, _MAX_PER_LIST)
    return {
        "standards": [{"cite": r["subject"], "text": r["value"], "page": r["page"]} for r in standards],
        "numbers": [{"subject": r["subject"], "text": r["value"], "page": r["page"]} for r in numbers],
        "terms": [{"term": r["subject"], "definition": r["value"], "page": r["page"]} for r in terms],
        "rules": [{"text": r["value"], "page": r["page"], "cfr": r["cfr"]} for r in rules],
        "steps": _steps(rules),
    }


def facts_for_prompt(con, lesson_id: int) -> dict:
    """The raw fact rows a scenario question may name (used by llm_gen for grounding)."""
    les = _lesson_row(con, lesson_id)
    module_id = les["module_id"]
    return {
        "terms": _lesson_terms(con, lesson_id, module_id, _MAX_PER_LIST),
        "numbers": _facts(con, ("threshold", "deadline"), lesson_id, module_id, _MAX_PER_LIST),
        "standards": _facts(con, ("cfr",), lesson_id, module_id, _MAX_PER_LIST),
        "rules": _facts(con, ("rule",), lesson_id, module_id, 6),
    }


# --- deterministic scenario ------------------------------------------------------------------

def _join_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def situation_for_lesson(con, lesson_id: int) -> str:
    """Names things only -- never states a fact. e.g. 'a situation involving guardrail
    systems, toeboards and a 42 inches requirement'."""
    f = facts_for_prompt(con, lesson_id)
    term_names = [t["subject"] for t in f["terms"][:2]]
    num_names = [n["subject"] for n in f["numbers"][:2]]
    names = [t.lower() if not t.isupper() else t for t in term_names]
    if not names and not num_names:
        return "a situation the lesson's rules cover"
    out = "a situation involving " + _join_names(names) if names else "a situation"
    if num_names:
        out += f" where the {_join_names(num_names)} figure{'s' if len(num_names) > 1 else ''} from the guide matter"
    return out


def deterministic_scenario(con, lesson_id: int) -> dict:
    les = _lesson_row(con, lesson_id)
    title = f"{les['topic']}: {les['label']}"
    prompt = _PROMPT_TEMPLATE.format(
        topic=les["topic"], lesson=les["label"], situation=situation_for_lesson(con, lesson_id)
    )
    return {
        "sid": make_sid("det", lesson_id, title),
        "module_id": les["module_id"],
        "lesson_id": lesson_id,
        "title": title,
        "prompt": prompt,
        "answer_json": json.dumps(answer_for_lesson(con, lesson_id)),
        "origin": "deterministic",
    }


def _insert(con, sc: dict) -> bool:
    cur = con.execute(
        "INSERT OR IGNORE INTO scenarios (sid, module_id, lesson_id, title, prompt, answer_json, origin) "
        "VALUES (?,?,?,?,?,?,?)",
        (sc["sid"], sc["module_id"], sc["lesson_id"], sc["title"], sc["prompt"],
         sc["answer_json"], sc["origin"]),
    )
    return cur.rowcount == 1


def load_ai_scenarios() -> list[dict]:
    path = paths.AI_SCENARIOS if hasattr(paths, "AI_SCENARIOS") else paths.DATA / "ai_scenarios.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("origin") == "ollama"]


def build_and_insert(con, ctx) -> dict:
    total = 0
    for les in ctx.lessons:
        if _insert(con, deterministic_scenario(con, les.id)):
            total += 1
    ai_n = 0
    for sc in load_ai_scenarios():
        needed = {"sid", "module_id", "lesson_id", "title", "prompt", "answer_json", "origin"}
        if not needed <= set(sc):
            continue
        if _insert(con, sc):
            total += 1
            ai_n += 1
    return {"scenarios": total, "ai_scenarios": ai_n}


if __name__ == "__main__":
    from .. import db
    _con = db.bank_connect(paths.BANK_DB)
    for _r in _con.execute("SELECT sid, origin, title, prompt FROM scenarios ORDER BY lesson_id LIMIT 3"):
        print(_r["sid"], _r["origin"], _r["title"])
        print("  ", _r["prompt"][:300])
