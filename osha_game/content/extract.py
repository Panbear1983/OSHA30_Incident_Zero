"""PDF -> data/cache/pages_*.jsonl, cached by file hash. PyMuPDF, build-time only."""
import hashlib
import json
from pathlib import Path
from .. import paths


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(pdf: Path, out: Path) -> list[str]:
    stamp = out.with_suffix(".sha1")
    sha = _sha1(pdf)
    if out.exists() and stamp.exists() and stamp.read_text().strip() == sha:
        return load_pages(out)
    import fitz  # deferred: pymupdf only needed when the cache is cold

    doc = fitz.open(pdf)
    pages = [page.get_text("text") for page in doc]
    with open(out, "w") as fh:
        for i, text in enumerate(pages, start=1):
            fh.write(json.dumps({"page": i, "text": text}) + "\n")
    stamp.write_text(sha)
    return pages


def load_pages(jsonl: Path) -> list[str]:
    """Returns page texts; index 0 is page 1."""
    rows = [json.loads(line) for line in open(jsonl)]
    rows.sort(key=lambda r: r["page"])
    return [r["text"] for r in rows]


def guide_pages() -> list[str]:
    paths.ensure_dirs()
    return _extract(paths.GUIDE_PDF, paths.PAGES_GUIDE)


def sds_pages() -> list[str]:
    paths.ensure_dirs()
    return _extract(paths.SDS_PDF, paths.PAGES_SDS)
