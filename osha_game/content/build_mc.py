"""Deterministic multiple-choice question builders.

Four categories, all kind='mc':
  glossary_fwd  -- "which definition matches this term"
  glossary_rev  -- "which term does this definition describe"
  cfr           -- forward (sentence -> 29 CFR standard) and reverse (standard -> topic)
  sds           -- forward (topic -> SDS section) and reverse (section -> topic)

Pure: build(ctx) -> list[Question]. No randomness, no I/O beyond what ctx already loaded,
no database access. Every ordering decision is a deterministic sort so a rebuild from the
same PDFs reproduces byte-identical output.
"""
import re

from .context import Context
from .mine import cfr_base, term_distractors
from .types import Question

# --- text helpers ------------------------------------------------------------

_PERIOD = re.compile(r"\.")

_TRUNC_LIMIT = 240
_TRUNC_HARD_LIMIT = 280


def _truncate(text: str, limit: int = _TRUNC_LIMIT, hard_limit: int = _TRUNC_HARD_LIMIT) -> str | None:
    """Truncate `text` at the nearest sentence boundary (a period followed by a space or
    the end of the string) at or before `limit` chars. Falls back to the nearest boundary
    before `hard_limit` if none exists at or before `limit`. Returns None if no sentence
    boundary at all exists before `hard_limit` (caller should skip rather than cut mid-sentence)."""
    if len(text) <= limit:
        return text
    boundaries = []
    for m in _PERIOD.finditer(text):
        cut = m.start() + 1
        if cut > hard_limit:
            break
        after = text[cut:cut + 1]
        if after == "" or after == " ":
            boundaries.append(cut)
    if not boundaries:
        return None
    at_or_before = [b for b in boundaries if b <= limit]
    cut = max(at_or_before) if at_or_before else max(boundaries)
    return text[:cut].rstrip()


def _first_sentence(text: str) -> str:
    """First sentence boundary regardless of position -- last-resort fallback when
    _truncate() can't find a clean cut within the hard limit."""
    for m in _PERIOD.finditer(text):
        cut = m.start() + 1
        after = text[cut:cut + 1]
        if after == "" or after == " ":
            return text[:cut].rstrip()
    return text


# --- glossary_fwd / glossary_rev ---------------------------------------------

def _build_glossary(ctx: Context) -> list[Question]:
    out: list[Question] = []
    for term, info in ctx.glossary.items():
        correct_def = _truncate(info["definition"])
        if correct_def is None:
            continue  # can't cut cleanly even at the hard limit -- skip this term entirely

        distractor_terms = term_distractors(ctx.glossary, ctx.homes, term, k=3)
        if len(distractor_terms) < 3:
            continue  # not enough glossary terms to build 4 distinct options

        page = info["page"]
        module_id = ctx.homes.get(term)

        # forward: term -> definition
        fwd_options = [correct_def]
        for other in distractor_terms:
            other_def = ctx.glossary[other]["definition"]
            trunc = _truncate(other_def)
            if trunc is None:
                trunc = _first_sentence(other_def)
            fwd_options.append(trunc)
        out.append(Question(
            kind="mc", category="glossary_fwd", module_id=module_id, lesson_id=None,
            prompt=f"Which definition matches: {term}",
            correct=correct_def,
            options=fwd_options,
            explanation=f"{term}: {correct_def}",
            cfr=None, page=page, source_doc="guide", source_quote=None,
            origin="deterministic",
        ))

        # reverse: definition -> term
        # (a literal newline separator would fail the validator's ASCII-only charset, so
        # the definition and the follow-up question are joined with a single space instead)
        rev_options = [term] + distractor_terms
        out.append(Question(
            kind="mc", category="glossary_rev", module_id=module_id, lesson_id=None,
            prompt=f"{correct_def} Which term is defined above?",
            correct=term,
            options=rev_options,
            explanation=f"{term}: {correct_def}",
            cfr=None, page=page, source_doc="guide", source_quote=correct_def,
            origin="deterministic",
        ))
    return out


# --- cfr (forward + reverse) --------------------------------------------------

def _cfr_num(base: str) -> int:
    return int(base.split(".", 1)[1])


def _build_cfr(ctx: Context) -> list[Question]:
    canon: dict[str, tuple[str, str, int]] = {}
    order: list[str] = []
    for cite, sentence, page in ctx.cfr_cites:
        base = cfr_base(cite)
        if base not in canon:
            canon[base] = (cite, sentence, page)
            order.append(base)
    all_bases = order

    out: list[Question] = []
    for base in all_bases:
        cite, sentence, page = canon[base]
        num = _cfr_num(base)
        mod = ctx.module_of(page)

        # forward: sentence -> "29 CFR {base}"
        others = [b for b in all_bases if b != base]
        if len(others) >= 3:
            others_sorted = sorted(others, key=lambda b: (abs(_cfr_num(b) - num), b))
            distractor_bases = others_sorted[:3]
            correct = f"29 CFR {base}"
            options = [correct] + [f"29 CFR {b}" for b in distractor_bases]
            out.append(Question(
                kind="mc", category="cfr",
                module_id=(mod.id if mod else None), lesson_id=None,
                prompt=f'Which OSHA standard is referenced here: "{sentence}"?',
                correct=correct,
                options=options,
                explanation=sentence,
                cfr=cite, page=page, source_doc="guide", source_quote=sentence,
                origin="deterministic",
            ))

        # reverse: "29 CFR {base}" -> topic (only if the page resolves to a real module)
        if mod is not None:
            other_mods = sorted(
                (m for m in ctx.modules if m.id != mod.id),
                key=lambda m: (abs(m.id - mod.id), m.id),
            )
            distractor_mods = other_mods[:3]
            if len(distractor_mods) == 3:
                rcorrect = mod.topic
                roptions = [rcorrect] + [m.topic for m in distractor_mods]
                out.append(Question(
                    kind="mc", category="cfr", module_id=mod.id, lesson_id=None,
                    prompt=f"29 CFR {base} is addressed under which topic?",
                    correct=rcorrect,
                    options=roptions,
                    explanation=sentence,
                    cfr=cite, page=page, source_doc="guide", source_quote=sentence,
                    origin="deterministic",
                ))
    return out


# --- sds (forward + reverse) --------------------------------------------------

SDS_SECTIONS = [
    (1, "IDENTIFICATION OF THE SUBSTANCE/PREPARATION AND OF THE COMPANY/UNDERTAKING", 1),
    (2, "HAZARDS IDENTIFICATION", 2),
    (3, "COMPOSITION/INFORMATION ON INGREDIENTS", 3),
    (4, "FIRST AID MEASURES", 3),
    (5, "FIRE-FIGHTING MEASURES", 4),
    (6, "ACCIDENTAL RELEASE MEASURES", 4),
    (7, "HANDLING AND STORAGE", 5),
    (8, "EXPOSURE CONTROLS/PERSONAL PROTECTION", 5),
    (9, "PHYSICAL AND CHEMICAL PROPERTIES", 6),
    (10, "STABILITY AND REACTIVITY", 6),
    (11, "TOXICOLOGICAL INFORMATION", 7),
    (12, "ECOLOGICAL INFORMATION", 8),
    (13, "DISPOSAL CONSIDERATIONS", 8),
    (14, "TRANSPORT INFORMATION", 8),
    (15, "REGULATORY INFORMATION", 9),
    (16, "OTHER INFORMATION", 10),
]

_SDS_MODULE_ID = 8  # Hazard Communication -- where SDS content lives


def _sds_hint(header: str) -> str:
    hint = header.lower().replace("/", " and ").replace("-", " ")
    return re.sub(r"\s+", " ", hint).strip()


def _sds_closest(num: int, all_nums: list[int], k: int = 3) -> list[int]:
    others = [n for n in all_nums if n != num]
    others.sort(key=lambda n: (abs(n - num), n))
    return others[:k]


def _build_sds(ctx: Context) -> list[Question]:
    by_num = {num: (header, page) for num, header, page in SDS_SECTIONS}
    all_nums = [num for num, _, _ in SDS_SECTIONS]

    out: list[Question] = []
    for num, header, page in SDS_SECTIONS:
        hint = _sds_hint(header)
        title = f"Section {num}: {header.title()}"
        quote = f"{num}. {header}"
        closest = _sds_closest(num, all_nums)

        # forward: hint -> section title
        fwd_options = [title] + [f"Section {n}: {by_num[n][0].title()}" for n in closest]
        out.append(Question(
            kind="mc", category="sds", module_id=_SDS_MODULE_ID, lesson_id=None,
            prompt=f"Which SDS section covers {hint}?",
            correct=title,
            options=fwd_options,
            explanation=f"Section {num} of a Safety Data Sheet covers {hint}.",
            cfr=None, page=page, source_doc="sds", source_quote=quote,
            origin="deterministic",
        ))

        # reverse: section number -> hint
        rev_correct = hint[0].upper() + hint[1:]
        rev_options = [rev_correct]
        for n in closest:
            h2 = _sds_hint(by_num[n][0])
            rev_options.append(h2[0].upper() + h2[1:])
        out.append(Question(
            kind="mc", category="sds", module_id=_SDS_MODULE_ID, lesson_id=None,
            prompt=f"Section {num} of a Safety Data Sheet addresses which of the following?",
            correct=rev_correct,
            options=rev_options,
            explanation=f"Section {num}: {header.title()}.",
            cfr=None, page=page, source_doc="sds", source_quote=quote,
            origin="deterministic",
        ))
    return out


# --- entry point ---------------------------------------------------------------

def build(ctx: Context) -> list[Question]:
    out: list[Question] = []
    out.extend(_build_glossary(ctx))
    out.extend(_build_cfr(ctx))
    out.extend(_build_sds(ctx))
    return out


if __name__ == "__main__":
    from collections import Counter
    from .context import build_context

    _ctx = build_context()
    _qs = build(_ctx)
    print("total:", len(_qs))
    print(Counter(q.category for q in _qs))
    for _q in _qs[:8]:
        print("---")
        print("kind:", _q.kind, "category:", _q.category, "page:", _q.page, "module_id:", _q.module_id)
        print("prompt:", _q.prompt[:150])
        print("correct:", _q.correct)
        print("options:", _q.options)
