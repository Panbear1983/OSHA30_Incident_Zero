"""The gate every Question passes through before insertion. Nothing bypasses this.

Checks: option shape, blank-marker shape, length bounds, a whitelisted charset (this is
the mechanical enforcement of "no emojis"), and a page-literal grounding check — the
answer must actually be findable on the page it cites. 'imported' origin gets a warn-only
grounding check (the seed cards' pageRefs are hand-typed and loose).
"""
import json
import re
from dataclasses import dataclass
from . import extract
from .norm import normalize, norm_cf, loose
from .qid import make_qid
from .types import Question

# ASCII + a small whitelist of punctuation/symbols the guide actually uses.
_CHARSET = re.compile(r"^[\x20-\x7E§°–—''–—‘’“”✓▪■]*$")

BLANK_MARKER = "____"


@dataclass
class Report:
    accepted: int = 0
    rejected: int = 0
    warnings: int = 0
    by_category: dict = None
    reasons: dict = None
    inserted_qids: list = None

    def __post_init__(self):
        self.by_category = self.by_category or {}
        self.reasons = self.reasons or {}
        self.inserted_qids = self.inserted_qids or []


def _charset_ok(*texts: str) -> bool:
    return all(_CHARSET.match(t) for t in texts)


def _page_text_cache() -> dict[tuple[str, int], str]:
    guide = extract.guide_pages()
    sds = extract.sds_pages()
    cache = {}
    for i, t in enumerate(guide, start=1):
        cache[("guide", i)] = loose(t)
    for i, t in enumerate(sds, start=1):
        cache[("sds", i)] = loose(t)
    return cache


def grounded(q: Question, page_cache: dict[tuple[str, int], str]) -> bool:
    if q.page is None:
        return False
    page_text = page_cache.get((q.source_doc, q.page), "")
    if not page_text:
        return False
    needle = loose(q.source_quote or q.correct)
    if len(needle) > 400:
        needle = needle[:400]
    return needle in page_text


def structural_check(q: Question) -> str | None:
    """Returns a reject reason, or None if structurally sound."""
    if q.kind not in ("mc", "blank"):
        return "bad_kind"
    if len(q.options) != 4:
        return "option_count"
    norm_opts = [norm_cf(o) for o in q.options]
    if len(set(norm_opts)) != 4:
        return "duplicate_options"
    if norm_cf(q.correct) not in norm_opts:
        return "answer_not_in_options"
    if not (20 <= len(q.prompt) <= 500):
        return "prompt_length"
    if any(not (1 <= len(o) <= 280) for o in q.options):
        return "option_length"
    if q.kind == "blank":
        if q.prompt.count(BLANK_MARKER) != 1:
            return "blank_marker_count"
    else:
        if BLANK_MARKER in q.prompt:
            return "blank_marker_in_mc"
    if not _charset_ok(q.prompt, q.correct, *q.options, q.explanation or ""):
        return "charset"
    return None


def validate_all(bank_con, questions: list[Question], insert: bool = True) -> Report:
    report = Report()
    page_cache = _page_text_cache() if any(q.page is not None for q in questions) else {}
    seen_this_run: set[str] = set()

    for q in questions:
        report.by_category[q.category] = report.by_category.get(q.category, 0)
        reason = structural_check(q)
        if reason is None and q.page is not None:
            ok = grounded(q, page_cache)
            if not ok:
                if q.origin == "imported":
                    report.warnings += 1
                else:
                    reason = "not_grounded_on_page"

        if reason:
            report.rejected += 1
            report.reasons[reason] = report.reasons.get(reason, 0) + 1
            continue

        qid = make_qid(q.kind, q.category, q.prompt, q.correct)
        if qid in seen_this_run:
            report.rejected += 1
            report.reasons["duplicate_in_batch"] = report.reasons.get("duplicate_in_batch", 0) + 1
            continue
        seen_this_run.add(qid)

        report.accepted += 1
        report.by_category[q.category] += 1
        if insert:
            bank_con.execute(
                "INSERT OR IGNORE INTO questions "
                "(qid, kind, category, module_id, lesson_id, prompt, correct, options, "
                " explanation, cfr, page, source_doc, source_quote, origin) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (qid, q.kind, q.category, q.module_id, q.lesson_id, q.prompt, q.correct,
                 json.dumps(q.options), q.explanation, q.cfr, q.page, q.source_doc,
                 q.source_quote, q.origin),
            )
            report.inserted_qids.append(qid)
    return report
