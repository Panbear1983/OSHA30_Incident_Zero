"""The one shape every builder returns. Builders never touch the database directly."""
from dataclasses import dataclass


@dataclass
class Question:
    kind: str            # 'mc' | 'blank'
    category: str        # glossary_fwd | glossary_rev | threshold | cfr | clock | sds | cloze | imported | scenario
    module_id: int | None
    lesson_id: int | None
    prompt: str
    correct: str
    options: list[str]   # exactly 4 strings, authoring order (UI shuffles at render time)
    explanation: str | None = None
    cfr: str | None = None
    page: int | None = None
    source_doc: str = "guide"   # 'guide' | 'sds'
    source_quote: str | None = None
    origin: str = "deterministic"   # 'deterministic' | 'ollama' | 'gemini' | 'imported'
