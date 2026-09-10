"""One shared text normalizer — miners, builders, and the validator must all use this,
so that grounding checks compare like with like."""
import re
import unicodedata

_WS = re.compile(r"\s+")
_MAP = {
    "­": "",    # soft hyphen
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "–": "-", "—": "-",
    " ": " ",
    "•": " ",   # bullet
    "": " ",   # Wingdings bullet (Word PDFs)
    "·": " ",
}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for k, v in _MAP.items():
        s = s.replace(k, v)
    return _WS.sub(" ", s).strip()


def norm_cf(s: str) -> str:
    return normalize(s).casefold()


def loose(s: str) -> str:
    """Hyphen-insensitive casefold — for grounding checks only."""
    return _WS.sub(" ", norm_cf(s).replace("-", " ")).strip()


_HEADER = re.compile(r"General Industry Outreach\s*(?:—|-)?\s*Study Guide")


def strip_boilerplate(page_text: str) -> str:
    """Drop the repeating page header/footer lines and lone bullets from raw page text."""
    out = []
    for line in page_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADER.search(stripped):
            continue
        if stripped.isdigit():
            continue
        if stripped in {"•", "", "·", "-"}:
            continue
        out.append(line)
    return "\n".join(out)
