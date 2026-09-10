"""Import the 30 hand-written cards in cards_data.json as Question objects.

This is a straight format-conversion builder: it does not mine the PDFs
itself (it consumes ctx only to resolve module_id), and it never reads or
writes cards_data.json's siblings from the earlier hand-built attempt
(build_game.py / osha_flashcard_game.html / osha_quiz_cli.py) -- those are
left completely alone.

source_quote is deliberately left None: these cards' pageRefs are hand-typed
and loose, and validate.py already treats a grounding failure for
origin='imported' as a warning rather than a hard reject, so forcing a
literal-substring match here would be fighting the validator's own design.
"""
import json
import re
from pathlib import Path

from .types import Question

# Project root is three levels up from this file (osha_game/content/importer.py).
CARDS_PATH = Path(__file__).resolve().parents[2] / "cards_data.json"

_MODULE_NUM = re.compile(r"Mod\s+(\d+)")
_PAGE_NUM = re.compile(r"(\d+)")


def _parse_module_id(module_str: str, valid_ids: set) -> "int | None":
    m = _MODULE_NUM.search(module_str or "")
    if not m:
        return None
    mid = int(m.group(1))
    return mid if mid in valid_ids else None


def _parse_page(page_ref: str) -> "int | None":
    m = _PAGE_NUM.search(page_ref or "")
    if not m:
        return None
    return int(m.group(1))


def build(ctx) -> list:
    """Pure conversion of cards_data.json -> list[Question]. Deterministic:
    iterates the JSON array in file order, no randomness, no DB access."""
    if not CARDS_PATH.exists():
        return []
    try:
        raw = CARDS_PATH.read_text(encoding="utf-8")
        cards = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(cards, list):
        return []

    valid_module_ids = {m.id for m in ctx.modules}
    questions: list[Question] = []

    for card in cards:
        if not isinstance(card, dict):
            continue

        options = card.get("options")
        if not isinstance(options, list) or len(options) != 4:
            continue

        answer_index = card.get("answerIndex")
        if not isinstance(answer_index, int) or isinstance(answer_index, bool) \
                or not (0 <= answer_index < 4):
            continue
        correct = options[answer_index]

        prompt = card.get("question")
        if not isinstance(prompt, str) or not prompt:
            continue

        module_id = _parse_module_id(card.get("module", ""), valid_module_ids)
        page = _parse_page(card.get("pageRef", ""))

        questions.append(Question(
            kind="mc",
            category="imported",
            module_id=module_id,
            lesson_id=None,
            prompt=prompt,
            correct=correct,
            options=list(options),
            explanation=card.get("explanation"),
            cfr=card.get("cfr"),
            page=page,
            source_doc="guide",
            source_quote=None,
            origin="imported",
        ))

    return questions


if __name__ == "__main__":
    from .context import build_context
    from collections import Counter

    ctx = build_context()
    qs = build(ctx)
    print("total:", len(qs))
    print(Counter(q.category for q in qs))
    print(Counter(q.kind for q in qs))
    print(Counter(q.origin for q in qs))
    resolved = [q.module_id for q in qs if q.module_id is not None]
    print("module_id resolved:", len(resolved), "sample:", resolved[:8])
    for q in qs[:3]:
        print("---")
        print(q.page, q.module_id, q.prompt[:80])
