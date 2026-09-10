"""Split the 966-page guide into 23 modules / 56 lessons with page ranges.

The PDF has no embedded bookmarks; body headings match a verified regex
(79 hits: 23 modules + 56 lessons). The printed TOC on pages 2-6 is skipped.
"""
import re
from dataclasses import dataclass, field

_MODULE = re.compile(r"^\s*Module\s+(\d+):\s*(.+?)\s*$")
_LESSON = re.compile(r"^\s*Lesson\s+(\d+):\s*(.+?)\s*$")
_SUMMARY = re.compile(r"^\s*Course Summary\s*$")

# Canonical titles from the printed TOC (regex headings can be truncated at line wraps).
TITLES = {
    1: "Introduction to OSHA",
    2: "Managing Safety and Health",
    3: "Walking & Working Surfaces",
    4: "Exit Routes, Emergency Action Plans, Fire Prevention Plans, and Fire Protection",
    5: "Electrical",
    6: "Personal Protective Equipment",
    7: "Materials Handling",
    8: "Hazard Communication",
    9: "Hazardous Materials",
    10: "Permit-Required Confined Space",
    11: "Lockout/Tagout",
    12: "Machine Guarding",
    13: "Welding and Cutting",
    14: "Introduction to Industrial Hygiene",
    15: "Bloodborne Pathogens",
    16: "Ergonomics",
    17: "Fall Protection",
    18: "Safety and Health Programs",
    19: "OSHA Recordkeeping",
    20: "Process Safety Management",
    21: "Asbestos in Workplace",
    22: "Scaffolds",
    23: "HAZWOPER",
}

# Short forms used as answer options ("which standard covers X").
TOPICS = {
    1: "Introduction to OSHA",
    2: "Managing Safety and Health",
    3: "Walking and Working Surfaces",
    4: "Exit Routes and Fire Protection",
    5: "Electrical Safety",
    6: "Personal Protective Equipment",
    7: "Materials Handling",
    8: "Hazard Communication",
    9: "Hazardous Materials",
    10: "Permit-Required Confined Spaces",
    11: "Lockout/Tagout",
    12: "Machine Guarding",
    13: "Welding and Cutting",
    14: "Industrial Hygiene",
    15: "Bloodborne Pathogens",
    16: "Ergonomics",
    17: "Fall Protection",
    18: "Safety and Health Programs",
    19: "OSHA Recordkeeping",
    20: "Process Safety Management",
    21: "Asbestos",
    22: "Scaffolds",
    23: "HAZWOPER",
}

GLOSSARY_PAGES = (8, 31)  # "Key Terms", verified


@dataclass
class Module:
    id: int
    title: str
    topic: str
    page_start: int
    page_end: int = 0
    lessons: list = field(default_factory=list)


@dataclass
class Lesson:
    id: int
    module_id: int
    label: str
    page_start: int
    page_end: int = 0


def segment(pages: list[str]) -> tuple[list[Module], list[Lesson]]:
    """pages[0] is page 1. Only pages > 6 are scanned (2-6 hold the printed TOC)."""
    modules: list[Module] = []
    lessons: list[Lesson] = []
    summary_page = len(pages)
    for pno in range(7, len(pages) + 1):
        for line in pages[pno - 1].splitlines():
            m = _MODULE.match(line)
            if m:
                mid = int(m.group(1))
                modules.append(Module(
                    id=mid,
                    title=TITLES.get(mid, m.group(2)),
                    topic=TOPICS.get(mid, m.group(2)),
                    page_start=pno,
                ))
                continue
            l = _LESSON.match(line)
            if l and modules:
                lessons.append(Lesson(
                    id=len(lessons) + 1,
                    module_id=modules[-1].id,
                    label=f"Lesson {l.group(1)}: {l.group(2)}",
                    page_start=pno,
                ))
                continue
            if _SUMMARY.match(line) and pno > 100:
                summary_page = min(summary_page, pno)

    if len(modules) != 23:
        raise RuntimeError(f"segmentation drift: expected 23 modules, found {len(modules)}")
    if not (50 <= len(lessons) <= 60):
        raise RuntimeError(f"segmentation drift: expected ~56 lessons, found {len(lessons)}")
    if [m.id for m in modules] != sorted(m.id for m in modules):
        raise RuntimeError("segmentation drift: module ids out of order")

    for i, mod in enumerate(modules):
        nxt = modules[i + 1].page_start if i + 1 < len(modules) else summary_page
        mod.page_end = max(mod.page_start, nxt - 1)
    for i, les in enumerate(lessons):
        mod = next(m for m in modules if m.id == les.module_id)
        if i + 1 < len(lessons) and lessons[i + 1].module_id == les.module_id:
            les.page_end = max(les.page_start, lessons[i + 1].page_start - 1)
        else:
            les.page_end = mod.page_end
        mod.lessons.append(les)
    return modules, lessons


def module_of_page(modules: list[Module], page: int):
    for mod in modules:
        if mod.page_start <= page <= mod.page_end:
            return mod
    return None
