"""Fact miners: glossary terms, sentences with page attribution, number+unit spans, CFR cites."""
import re
from .norm import normalize, norm_cf, strip_boilerplate
from .segment import GLOSSARY_PAGES

# --- glossary ---------------------------------------------------------------

_TERM = re.compile(r"^([A-Z][A-Za-z0-9 ,\-/()'&]{2,60}):\s", re.M)


def glossary(pages: list[str]) -> dict[str, dict]:
    """Key Terms pages -> {term: {definition, page}}. The glossary is alphabetical, so any
    candidate that breaks casefold order (e.g. an inline 'Note:') is a false positive."""
    lo, hi = GLOSSARY_PAGES
    buf, offsets = "", []
    for pno in range(lo, hi + 1):
        offsets.append((len(buf), pno))
        buf += strip_boilerplate(pages[pno - 1]) + "\n"

    kept, last_cf = [], ""
    for m in _TERM.finditer(buf):
        cf = m.group(1).strip().casefold()
        if kept and cf < last_cf:
            continue
        kept.append(m)
        last_cf = cf

    def page_at(pos: int) -> int:
        page = offsets[0][1]
        for off, pno in offsets:
            if off <= pos:
                page = pno
        return page

    terms: dict[str, dict] = {}
    for i, m in enumerate(kept):
        term = normalize(m.group(1))
        end = kept[i + 1].start() if i + 1 < len(kept) else len(buf)
        definition = normalize(buf[m.end():end])
        if len(definition) < 10:
            continue
        terms[term] = {"definition": definition, "page": page_at(m.start())}
    return terms


def term_home_modules(terms: dict, body_norm: list[tuple[int, str]], modules) -> dict[str, int | None]:
    """First whole-word body occurrence of each term -> its module id (None if never used)."""
    from .segment import module_of_page
    homes: dict[str, int | None] = {}
    for term in terms:
        pat = re.compile(r"\b" + re.escape(term.casefold()) + r"\b")
        home = None
        for pno, text in body_norm:
            if pat.search(text):
                mod = module_of_page(modules, pno)
                home = mod.id if mod else None
                break
        homes[term] = home
    return homes


# --- sentences --------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")
_STOPWORDS = re.compile(
    r"\b(the|a|an|of|to|in|is|are|that|which|and|or|for|with|by|on|as|be|must|"
    r"shall|when|if|this|these|will|can|not|may)\b", re.I)


_WORD = re.compile(r"[A-Za-z']+")


def _looks_like_prose(s: str) -> bool:
    """Rejects concatenated bullet-list fragments (Title Case Title Case ...) that the PDF's
    lack of terminal punctuation lets slip past the sentence splitter: those read as a run
    of capitalized words with almost no lowercase connective tissue."""
    words = _WORD.findall(s)
    if len(words) < 8 or len(_STOPWORDS.findall(s)) < 4:
        return False
    tail = words[1:]
    cap_ratio = sum(1 for w in tail if w[0].isupper()) / len(tail)
    return cap_ratio <= 0.35


def sentences_in(pages: list[str], p_start: int, p_end: int,
                 min_len: int = 60, max_len: int = 220) -> list[tuple[str, int]]:
    """(sentence, page) pairs. Sentences that span a page break are dropped on purpose —
    plenty remain, and page attribution stays exact."""
    out = []
    for pno in range(p_start, p_end + 1):
        text = normalize(strip_boilerplate(pages[pno - 1]))
        for s in _SENT_SPLIT.split(text):
            s = s.strip()
            if min_len <= len(s) <= max_len and re.search(r"[A-Za-z]{3}", s) and _looks_like_prose(s):
                out.append((s, pno))
    return out


# --- numbers + units --------------------------------------------------------

_UNITS = (
    "working days|feet|foot|ft|inches|inch|pounds|pound|lbs|hours|hour|days|day|"
    "years|year|degrees Fahrenheit|°F|degrees|percent|%|ppm|dBA|dB|volts|volt|"
    "milliamperes|amperes|ampere|amps|mA|psig|psi"
)
NUMUNIT = re.compile(rf"(?<![\w.§])(\d[\d,]*(?:\.\d+)?)\s*({_UNITS})(?![A-Za-z])")

UNIT_FAMILY = {
    "feet": "feet", "foot": "feet", "ft": "feet",
    "inches": "inches", "inch": "inches",
    "pounds": "pounds", "pound": "pounds", "lbs": "pounds",
    "hours": "hours", "hour": "hours",
    "days": "days", "day": "days", "working days": "days",
    "years": "years", "year": "years",
    "degrees fahrenheit": "degrees", "°f": "degrees", "degrees": "degrees",
    "percent": "percent", "%": "percent",
    "ppm": "ppm", "dba": "db", "db": "db",
    "volts": "volts", "volt": "volts",
    "milliamperes": "amperes", "amperes": "amperes", "ampere": "amperes",
    "amps": "amperes", "ma": "amperes",
    "psig": "psi", "psi": "psi",
}

TIME_FAMILIES = {"hours", "days", "years"}


def num_value(text: str) -> float:
    return float(text.replace(",", ""))


def fmt_num(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:g}"


# --- CFR citations ----------------------------------------------------------

CFR = re.compile(r"\b(19(?:10|26)\.\d+(?:\([a-zA-Z0-9]+\))*)")


def cfr_base(cite: str) -> str:
    return cite.split("(")[0]


def cfr_mentions(pages: list[str], p_start: int = 7, p_end: int | None = None) -> list[tuple[str, str, int]]:
    """(cfr_cite, sentence, page) for every sentence in the body that names a CFR cite."""
    p_end = p_end or len(pages)
    out = []
    for pno in range(p_start, p_end + 1):
        text = normalize(strip_boilerplate(pages[pno - 1]))
        for s in _SENT_SPLIT.split(text):
            s = s.strip()
            if len(s) < 20 or not _looks_like_prose(s):
                continue
            m = CFR.search(s)
            if m:
                out.append((m.group(1), s, pno))
    return out


def term_distractors(glossary: dict, homes: dict, term: str, k: int = 3) -> list[str]:
    """k other glossary terms scored by likely confusability: same home module, same
    first letter, similar definition length. Deterministic (no RNG) so a rebuild of the
    bank from the same PDF always reproduces the same content — render-time shuffling in
    the UI is what keeps actual play unpredictable, not the build."""
    target_def = glossary[term]["definition"]
    target_home = homes.get(term)
    target_letter = term[:1].casefold()
    scored = []
    for other, info in glossary.items():
        if other == term:
            continue
        score = 0
        if homes.get(other) is not None and homes.get(other) == target_home:
            score += 2
        if other[:1].casefold() == target_letter:
            score += 1
        if abs(len(info["definition"]) - len(target_def)) <= 0.4 * max(len(target_def), 1):
            score += 1
        scored.append((-score, other))
    scored.sort()
    return [t for _, t in scored[:k]]


# Fallback numeric ladders, used only when a unit family has too few distinct mined
# values to build 3 clean distractors. Plausible OSHA-style round numbers per family.
FALLBACK_LADDERS = {
    "feet": [2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 35, 40, 42, 48, 50],
    "inches": [4, 6, 8, 12, 18, 24, 30, 36, 42, 48],
    "pounds": [50, 100, 250, 500, 1000, 2000, 4000, 5000, 10000],
    "hours": [1, 2, 4, 8, 12, 24, 48, 72],
    "days": [1, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90],
    "years": [1, 2, 3, 5, 10, 20, 30],
    "degrees": [32, 68, 73.4, 100, 104, 122, 140, 150, 165, 199.4, 200, 250],
    "percent": [5, 10, 15, 20, 25, 30, 50, 75, 90, 95],
    "ppm": [5, 10, 25, 50, 100, 250, 500, 1000],
    "db": [80, 85, 90, 95, 100, 105, 110, 115],
    "volts": [24, 50, 120, 208, 240, 277, 480, 600],
    "amperes": [1, 5, 10, 15, 20, 30, 60, 100],
    "psi": [15, 25, 50, 100, 125, 150, 200, 250],
}
