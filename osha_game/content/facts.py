"""The shared fact base: every number, defined term, regulation reference, SDS section, and
"must/shall" rule the guide states, each carrying the page it came from and a verbatim quote.

Every screen outside Train (Look Up, Inspect, Interview) reads facts -- none of them mines
the PDF themselves, so they can never disagree about what page something is on.

Pure: build(ctx) -> list[Fact]. No randomness, no I/O, no database access, no LLM.
"""
import hashlib
import re
from dataclasses import dataclass

from . import mine
from .build_blank import _CLOCK_KEYWORDS
from .build_mc import SDS_SECTIONS, _sds_hint, _SDS_MODULE_ID
from .norm import normalize, norm_cf, strip_boilerplate

KINDS = ("term", "threshold", "deadline", "cfr", "rule", "sds")


@dataclass
class Fact:
    kind: str                 # one of KINDS
    subject: str              # the term / "42 inches" / "29 CFR 1910.147" / lesson label / SDS section
    value: str                # definition / the sentence stating the number / the rule sentence / hint
    quote: str                # verbatim text that must appear on `page` (grounding check)
    page: int
    module_id: int | None
    lesson_id: int | None
    cfr: str | None = None
    number: float | None = None
    unit: str | None = None   # unit family for threshold/deadline (feet, inches, days ...)
    source_doc: str = "guide"  # 'guide' | 'sds'

    @property
    def fid(self) -> str:
        key = f"{self.kind}|{norm_cf(self.subject)}|{norm_cf(self.quote)}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


# --- line-aware sentence extraction --------------------------------------------------------
#
# mine.sentences_in() joins a page's lines with spaces before splitting, so a heading line
# ("Safe Work Condition") that has no terminal punctuation gets glued onto the sentence that
# follows it. Facts are shown to the reader verbatim, so headings are dropped line-by-line
# here first. Train's builders are deliberately left on the old path (unchanged bank).

_HEADING_END = re.compile(r"[.!?:;,]\s*$")
_PAREN_SPLIT = re.compile(r"(?<=[.!?]\))\s+(?=[A-Z0-9\"(])")   # "...methods.) Some ..."
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_RULE_WORDS = re.compile(r"\b(must|shall)\b", re.I)


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 80 or _HEADING_END.search(s):
        return False
    if s.startswith(("\u2022", "\uf0b7", "-", "\u00b7")):   # bullets (incl. Wingdings) never head
        return False
    words = _WORD.findall(s)
    if not (1 <= len(words) <= 10):
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.6


def clean_sentences(pages: list[str], p_start: int, p_end: int,
                    min_len: int = 40, max_len: int = 260, prose: bool = True) -> list[tuple[str, int]]:
    """(sentence, page) pairs with heading lines removed before joining. Sentences that span
    a page break are dropped on purpose so page attribution stays exact."""
    out: list[tuple[str, int]] = []
    for pno in range(p_start, p_end + 1):
        body = strip_boilerplate(pages[pno - 1])
        kept = [ln for ln in body.splitlines() if not _is_heading(ln)]
        text = normalize("\n".join(kept))
        for s in (b for a in mine._SENT_SPLIT.split(text) for b in _PAREN_SPLIT.split(a)):
            s = s.strip()
            if not (min_len <= len(s) <= max_len) or not re.search(r"[A-Za-z]{3}", s):
                continue
            if prose and not mine._looks_like_prose(s):
                continue
            out.append((s, pno))
    return out


# --- builders ------------------------------------------------------------------------------

def _terms(ctx) -> list[Fact]:
    out = []
    for term, info in ctx.glossary.items():
        out.append(Fact(
            kind="term", subject=term, value=info["definition"], quote=info["definition"],
            page=info["page"], module_id=ctx.homes.get(term), lesson_id=None,
        ))
    return out


def _numbers(ctx) -> list[Fact]:
    out: list[Fact] = []
    seen: set[tuple[str, str]] = set()
    for mod in ctx.modules:
        for les in mod.lessons:
            for sentence, page in clean_sentences(ctx.guide_pages, les.page_start, les.page_end):
                for m in mine.NUMUNIT.finditer(sentence):
                    family = mine.UNIT_FAMILY.get(m.group(2).lower().rstrip("."))
                    if family is None:
                        continue
                    key = (sentence, m.group(0))
                    if key in seen:
                        continue
                    seen.add(key)
                    low = sentence.casefold()
                    is_deadline = family in mine.TIME_FAMILIES and any(k in low for k in _CLOCK_KEYWORDS)
                    m_cfr = mine.CFR.search(sentence)
                    out.append(Fact(
                        kind="deadline" if is_deadline else "threshold",
                        subject=m.group(0), value=sentence, quote=sentence, page=page,
                        module_id=mod.id, lesson_id=les.id,
                        cfr=m_cfr.group(1) if m_cfr else None,
                        number=mine.num_value(m.group(1)), unit=family,
                    ))
    return out


def _cfrs(ctx) -> list[Fact]:
    """Every clean sentence in the body that names a CFR cite. (Not ctx.cfr_cites: that list
    comes from the line-joined miner and carries glued headings; facts are shown verbatim.)"""
    out: list[Fact] = []
    seen: set[tuple[str, str]] = set()
    for mod in ctx.modules:
        for les in mod.lessons:
            for sentence, page in clean_sentences(ctx.guide_pages, les.page_start, les.page_end,
                                                  min_len=20, max_len=300, prose=False):
                m = mine.CFR.search(sentence)
                if not m:
                    continue
                cite = m.group(1)
                key = (cite, sentence)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Fact(
                    kind="cfr", subject=f"29 CFR {cite}", value=sentence, quote=sentence,
                    page=page, module_id=mod.id, lesson_id=les.id, cfr=cite,
                ))
    return out


def _rules(ctx) -> list[Fact]:
    out: list[Fact] = []
    seen: set[str] = set()
    for mod in ctx.modules:
        for les in mod.lessons:
            for sentence, page in clean_sentences(ctx.guide_pages, les.page_start, les.page_end):
                if not _RULE_WORDS.search(sentence):
                    continue
                key = norm_cf(sentence)
                if key in seen:
                    continue
                seen.add(key)
                m_cfr = mine.CFR.search(sentence)
                out.append(Fact(
                    kind="rule", subject=les.label, value=sentence, quote=sentence, page=page,
                    module_id=mod.id, lesson_id=les.id, cfr=m_cfr.group(1) if m_cfr else None,
                ))
    return out


def _sds(ctx) -> list[Fact]:
    out = []
    for num, header, page in SDS_SECTIONS:
        hint = _sds_hint(header)
        out.append(Fact(
            kind="sds", subject=f"SDS Section {num}: {header.title()}",
            value=f"Section {num} of a Safety Data Sheet covers {hint}.",
            quote=f"{num}. {header}", page=page, module_id=_SDS_MODULE_ID, lesson_id=None,
            source_doc="sds",
        ))
    return out


def build(ctx) -> list[Fact]:
    out: list[Fact] = []
    out.extend(_terms(ctx))
    out.extend(_numbers(ctx))
    out.extend(_cfrs(ctx))
    out.extend(_rules(ctx))
    out.extend(_sds(ctx))
    return out


if __name__ == "__main__":
    from collections import Counter
    from .context import build_context

    _facts = build(build_context())
    print("total:", len(_facts))
    print(Counter(f.kind for f in _facts))
