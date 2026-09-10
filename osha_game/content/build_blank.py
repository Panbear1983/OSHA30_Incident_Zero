"""Deterministic fill-in-the-blank builder.

Three categories, all kind='blank':
  - threshold : a numeric span (e.g. "4 feet", "10 pounds") blanked out of a sentence
                that mentions exactly one number+unit.
  - clock     : same shape as threshold, but the unit is a time family (hours/days/years)
                AND the sentence is about a reporting/filing/retention deadline.
  - cloze     : a glossary term blanked out of a sentence (that has no numeric mention)
                which happens to use that term.

No randomness anywhere -- every distractor list and every iteration order is produced by
deterministic sorting, so rebuilding from the same PDF reproduces the same bank byte-for-byte.
"""
import re

from . import mine
from .norm import norm_cf
from .types import Question

# --- threshold / clock classification ---------------------------------------

_CLOCK_KEYWORDS = (
    "report", "notify", "notification", "contest", "retain", "retention",
    "record", "file a", "filing", "within",
)


def _unit_family(m: re.Match) -> str | None:
    unit_key = m.group(2).lower().rstrip(".")
    return mine.UNIT_FAMILY.get(unit_key)


def _record_from_match(sentence: str, page: int, lesson, module, m: re.Match) -> dict | None:
    family = _unit_family(m)
    if family is None:
        return None
    return {
        "sentence": sentence,
        "page": page,
        "lesson": lesson,
        "module": module,
        "matched_text": m.group(0),
        "number_text": m.group(1),
        "unit_text": m.group(2),
        "value": mine.num_value(m.group(1)),
        "family": family,
    }


def _is_clock(rec: dict) -> bool:
    if rec["family"] not in mine.TIME_FAMILIES:
        return False
    low = rec["sentence"].casefold()
    return any(kw in low for kw in _CLOCK_KEYWORDS)


def _pick_distractor_values(rec: dict, pool_by_family: dict) -> list[float] | None:
    """3 nearest distinct values (by absolute distance, ties ascending) from the global
    pool for this record's unit family, topped up from FALLBACK_LADDERS if the pool is
    too thin. Returns None if 3 distinct values still can't be found."""
    family = rec["family"]
    own = rec["value"]
    pool = pool_by_family.get(family, [])

    chosen: list[float] = []
    candidates = sorted((v for v in pool if v != own), key=lambda v: (abs(v - own), v))
    for v in candidates:
        chosen.append(v)
        if len(chosen) == 3:
            break

    if len(chosen) < 3:
        ladder = mine.FALLBACK_LADDERS.get(family, [])
        extra = sorted(
            (v for v in ladder if v != own and v not in chosen),
            key=lambda v: (abs(v - own), v),
        )
        for v in extra:
            chosen.append(v)
            if len(chosen) == 3:
                break

    if len(chosen) < 3:
        return None
    return chosen[:3]


def _build_numeric_question(rec: dict, pool_by_family: dict) -> Question | None:
    sentence = rec["sentence"]
    matched_text = rec["matched_text"]
    if matched_text not in sentence:
        return None

    values = _pick_distractor_values(rec, pool_by_family)
    if values is None:
        return None

    unit_word = rec["unit_text"]
    correct = matched_text
    options = [correct] + [f"{mine.fmt_num(v)} {unit_word}" for v in values]
    if len({norm_cf(o) for o in options}) != 4:
        return None

    prompt = sentence.replace(matched_text, "____", 1)
    if prompt.count("____") != 1:
        return None

    category = "clock" if _is_clock(rec) else "threshold"
    m_cfr = mine.CFR.search(sentence)
    cfr = m_cfr.group(1) if m_cfr else None
    explanation = f'The standard states: "{sentence}"'
    if cfr:
        explanation += f" ({cfr})"

    lesson = rec["lesson"]
    return Question(
        kind="blank",
        category=category,
        module_id=lesson.module_id,
        lesson_id=lesson.id,
        prompt=prompt,
        correct=correct,
        options=options,
        explanation=explanation,
        cfr=cfr,
        page=rec["page"],
        source_doc="guide",
        source_quote=sentence,
        origin="deterministic",
    )


# --- cloze --------------------------------------------------------------------

_TERM_RX_CACHE: dict[str, re.Pattern] = {}


def _term_regex(term: str) -> re.Pattern:
    rx = _TERM_RX_CACHE.get(term)
    if rx is None:
        rx = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        _TERM_RX_CACHE[term] = rx
    return rx


def _truncate_definition(definition: str) -> str:
    """Truncate at a sentence boundary at/before 240 chars; if none, fall back to the
    first sentence if it ends before 280 chars; otherwise hard-cut at 240."""
    if len(definition) <= 240:
        return definition
    boundaries = [m.end() for m in re.finditer(r"[.!?]", definition)]
    at_or_before_240 = [b for b in boundaries if b <= 240]
    if at_or_before_240:
        return definition[:at_or_before_240[-1]].rstrip()
    if boundaries and boundaries[0] <= 280:
        return definition[:boundaries[0]].rstrip()
    return definition[:240].rstrip() + "..."


def _build_cloze_question(ctx, lesson, sentence: str, page: int, glossary_items: list) -> Question | None:
    matched_term = None
    match = None
    for term, _info in glossary_items:
        m = _term_regex(term).search(sentence)
        if m:
            matched_term = term
            match = m
            break
    if matched_term is None:
        return None

    prompt = sentence[:match.start()] + "____" + sentence[match.end():]
    if prompt.count("____") != 1:
        return None

    correct = matched_term
    distractors = mine.term_distractors(ctx.glossary, ctx.homes, matched_term, k=3)
    options = [correct] + distractors
    if len(options) != 4 or len({norm_cf(o) for o in options}) != 4:
        return None

    definition = ctx.glossary[matched_term]["definition"]
    explanation = f"{matched_term}: {_truncate_definition(definition)}"

    return Question(
        kind="blank",
        category="cloze",
        module_id=lesson.module_id,
        lesson_id=lesson.id,
        prompt=prompt,
        correct=correct,
        options=options,
        explanation=explanation,
        cfr=None,
        page=page,
        source_doc="guide",
        source_quote=sentence,
        origin="deterministic",
    )


# --- entry point ----------------------------------------------------------------

def build(ctx) -> list[Question]:
    candidates: list[dict] = []
    lesson_annotated: dict[int, list[tuple[str, int, int]]] = {}

    # One shared numeric scan: per-sentence NUMUNIT match counts, plus candidate records
    # for sentences with exactly one match and a recognized unit.
    for module in ctx.modules:
        for lesson in module.lessons:
            annotated: list[tuple[str, int, int]] = []
            for sentence, page in ctx.lesson_sentences(lesson):
                matches = list(mine.NUMUNIT.finditer(sentence))
                annotated.append((sentence, page, len(matches)))
                if len(matches) == 1:
                    rec = _record_from_match(sentence, page, lesson, module, matches[0])
                    if rec is not None:
                        candidates.append(rec)
            lesson_annotated[lesson.id] = annotated

    # Global pool: per unit family, sorted distinct numeric values seen anywhere.
    pool_sets: dict[str, set] = {}
    for rec in candidates:
        pool_sets.setdefault(rec["family"], set()).add(rec["value"])
    pool_by_family = {fam: sorted(vals) for fam, vals in pool_sets.items()}

    questions: list[Question] = []

    for rec in candidates:
        q = _build_numeric_question(rec, pool_by_family)
        if q is not None:
            questions.append(q)

    glossary_items = list(ctx.glossary.items())
    for module in ctx.modules:
        for lesson in module.lessons:
            made = 0
            for sentence, page, n_matches in lesson_annotated[lesson.id]:
                if made >= 6:
                    break
                if n_matches != 0:
                    continue
                q = _build_cloze_question(ctx, lesson, sentence, page, glossary_items)
                if q is not None:
                    questions.append(q)
                    made += 1

    return questions


if __name__ == "__main__":
    from collections import Counter

    from .context import build_context

    ctx = build_context()
    qs = build(ctx)
    print("total:", len(qs))
    print(Counter(q.category for q in qs))
