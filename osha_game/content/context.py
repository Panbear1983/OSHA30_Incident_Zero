"""Runs extraction + segmentation + mining ONCE and hands every builder the same facts,
so two builders can never disagree about what page something is on."""
from dataclasses import dataclass, field
from . import extract, mine
from .segment import Module, Lesson, segment, module_of_page
from .norm import normalize, strip_boilerplate

INTRO_PAGE = 32  # "Introduction" heading; body content proper starts here (Module 1 is p.34)


@dataclass
class Context:
    modules: list[Module]
    lessons: list[Lesson]
    guide_pages: list[str]              # index 0 = page 1
    sds_pages: list[str]
    glossary: dict[str, dict]           # term -> {definition, page}
    homes: dict[str, int | None]        # term -> module_id or None
    cfr_cites: list[tuple[str, str, int]]   # (cite, sentence, page)

    def module_of(self, page: int) -> Module | None:
        return module_of_page(self.modules, page)

    def lesson_of(self, page: int) -> Lesson | None:
        for les in self.lessons:
            if les.page_start <= page <= les.page_end:
                return les
        return None

    def lesson_sentences(self, lesson: Lesson, **kw) -> list[tuple[str, int]]:
        return mine.sentences_in(self.guide_pages, lesson.page_start, lesson.page_end, **kw)

    def lesson_text(self, lesson: Lesson) -> str:
        parts = [strip_boilerplate(self.guide_pages[p - 1]) for p in range(lesson.page_start, lesson.page_end + 1)]
        return normalize("\n".join(parts))


_cached: Context | None = None


def build_context(force: bool = False) -> Context:
    global _cached
    if _cached is not None and not force:
        return _cached
    guide_pages = extract.guide_pages()
    sds_pages = extract.sds_pages()
    modules, lessons = segment(guide_pages)
    glossary = mine.glossary(guide_pages)
    body_norm = [
        (pno, normalize(strip_boilerplate(guide_pages[pno - 1])))
        for pno in range(INTRO_PAGE, len(guide_pages) + 1)
    ]
    homes = mine.term_home_modules(glossary, body_norm, modules)
    cfr_cites = mine.cfr_mentions(guide_pages, p_start=INTRO_PAGE)
    _cached = Context(
        modules=modules, lessons=lessons, guide_pages=guide_pages, sds_pages=sds_pages,
        glossary=glossary, homes=homes, cfr_cites=cfr_cites,
    )
    return _cached
