"""Stable content-hash question id, so a bank rebuild never orphans a profile's progress
for a question whose text didn't actually change."""
import hashlib
from .norm import norm_cf


def make_qid(kind: str, category: str, prompt: str, correct: str) -> str:
    key = f"{kind}|{category}|{norm_cf(prompt)}|{norm_cf(correct)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
