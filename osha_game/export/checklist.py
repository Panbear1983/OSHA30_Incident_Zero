"""Word / PDF export of Inspect checklists into exports/ (git-ignored).

One document per module: the module title, the guide's own must/shall requirements grouped
under their lesson headings, each with a checkbox, its page, and its CFR cite when the
sentence names one. PDF conversion goes through LibreOffice when it is installed; the Word
file is always written. No names, no profile data, nothing personal ends up in the file.

  CLI:    ./dashboard.sh export [--module N | --all] [--no-pdf] [--out DIR]
          ./dashboard.sh export --checklist cable_pull | --qaqc     (QA/QC track lists)
  Screen: export_module(con, module_id, out_dir, pdf=True) -> list[Path]
          export_qaqc(con, key, out_dir, pdf=True) -> list[Path]
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import db, paths
from ..content.segment import TITLES, TOPICS

_SOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
    "libreoffice",
)

SUBTITLE = "OSHA 30 General Industry - inspection checklist"
INTRO = (
    "Every item below is one of the study guide's own must/shall requirements for this "
    "module, quoted as written, in the order the guide states them. The page number after "
    "each item refers to the study guide; a standard number is shown where the sentence "
    "names one."
)
FOOTER = (
    "Source: OSHA 30-Hour General Industry Outreach Study Guide, page numbers refer to that guide."
)


def soffice_path() -> str | None:
    """LibreOffice binary, or None when it is not installed."""
    for cand in _SOFFICE_CANDIDATES:
        if os.sep in cand:
            if os.access(cand, os.X_OK):
                return cand
        elif shutil.which(cand):
            return shutil.which(cand)
    return None


def _schema_prefix(con) -> str:
    """'bank.' when bank.db is ATTACHed (the game connection), '' on a bank-only one."""
    names = {r[1] for r in con.execute("PRAGMA database_list").fetchall()}
    return "bank." if "bank" in names else ""


def has_checklists(con) -> bool:
    s = _schema_prefix(con)
    row = con.execute(
        f"SELECT 1 FROM {s}sqlite_master WHERE type='table' AND name='checklist_items'"
    ).fetchone()
    if row is None:
        return False
    return con.execute(f"SELECT COUNT(*) FROM {s}checklist_items").fetchone()[0] > 0


def _items(con, module_id: int) -> list:
    s = _schema_prefix(con)
    return con.execute(
        f"SELECT c.seq, c.text, c.page, c.cfr, c.lesson_id, l.label AS lesson "
        f"FROM {s}checklist_items c LEFT JOIN {s}lessons l ON l.id = c.lesson_id "
        f"WHERE c.module_id=? ORDER BY c.seq",
        (module_id,),
    ).fetchall()


def file_stem(module_id: int) -> str:
    topic = TOPICS.get(module_id, f"Module {module_id}")
    safe = re.sub(r"[^A-Za-z0-9]+", "_", topic).strip("_")
    return f"Module_{module_id:02d}_{safe}_Checklist"


def _write_docx(module_id: int, items: list, out_path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Inches

    doc = Document()
    for section in doc.sections:
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)

    title = TITLES.get(module_id, f"Module {module_id}")
    doc.add_heading(f"Module {module_id}: {title}", level=0)
    sub = doc.add_paragraph(SUBTITLE)
    sub.runs[0].italic = True
    doc.add_paragraph(INTRO)

    current_lesson = object()
    table = None
    for it in items:
        lesson = it["lesson"] or "General"
        if lesson != current_lesson:
            current_lesson = lesson
            doc.add_heading(lesson, level=2)
            table = doc.add_table(rows=0, cols=3)
            table.style = "Table Grid"
            table.autofit = False
        row = table.add_row().cells
        row[0].width = Inches(0.45)
        row[1].width = Inches(5.2)
        row[2].width = Inches(1.25)
        row[0].text = "[ ]"
        row[1].text = it["text"]
        ref = f"p. {it['page']}"
        if it["cfr"]:
            ref += f"\n29 CFR {it['cfr']}"
        row[2].text = ref
        for cell in row:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(9.5)
        row[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.add_paragraph()
    foot = doc.add_paragraph(FOOTER)
    foot.runs[0].font.size = Pt(8)
    foot.runs[0].italic = True
    doc.save(str(out_path))


def _to_pdf(docx_path: Path, out_dir: Path) -> Path | None:
    binary = soffice_path()
    if binary is None:
        return None
    # A private profile dir per call: a LibreOffice GUI already open on the Mac would
    # otherwise swallow the headless request and return without writing anything.
    with tempfile.TemporaryDirectory(prefix="osha_soffice_") as profile:
        cmd = [
            binary, "--headless", "--norestore",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path),
        ]
        env = dict(os.environ)
        env["HOME"] = profile
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=120, env=env)
        except (subprocess.TimeoutExpired, OSError):
            return None
    pdf = out_dir / (docx_path.stem + ".pdf")
    return pdf if pdf.exists() and pdf.stat().st_size > 0 else None


def export_module(con, module_id: int, out_dir: Path, pdf: bool = True) -> list[Path]:
    """Write the module's checklist as Word (and PDF when LibreOffice is available).
    Returns the paths actually written; raises ValueError for a module with no items."""
    items = _items(con, module_id)
    if not items:
        raise ValueError(f"module {module_id} has no checklist items")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / (file_stem(module_id) + ".docx")
    _write_docx(module_id, items, docx_path)
    written = [docx_path]
    if pdf:
        pdf_path = _to_pdf(docx_path, out_dir)
        if pdf_path is not None:
            written.append(pdf_path)
    return written


def export_all(con, out_dir: Path, pdf: bool = True) -> list[Path]:
    s = _schema_prefix(con)
    ids = [r[0] for r in con.execute(
        f"SELECT DISTINCT module_id FROM {s}checklist_items ORDER BY module_id").fetchall()]
    written: list[Path] = []
    for mid in ids:
        written.extend(export_module(con, mid, out_dir, pdf=pdf))
    return written


# -- QA/QC track checklists (separate lists, cited to public web sources, not to the guide) --

QAQC_SUBTITLE = "QA/QC pre-start program - inspection checklist"
QAQC_FOOTER = ("Generic checklist built from public reference material; it does not replace the "
               "project specification, the approved ITP, or the manufacturer's instructions.")


def qaqc_keys(con) -> list[str]:
    s = _schema_prefix(con)
    try:
        return [r[0] for r in con.execute(f"SELECT key FROM {s}qaqc_checklists ORDER BY seq").fetchall()]
    except Exception:
        return []


def _qaqc_list(con, key: str):
    s = _schema_prefix(con)
    head = con.execute(f"SELECT key, module_id, title, intro FROM {s}qaqc_checklists WHERE key=?",
                       (key,)).fetchone()
    if head is None:
        return None, []
    items = con.execute(
        f"SELECT seq, section, text, source_url, source_label FROM {s}qaqc_checklist_items "
        f"WHERE list_key=? ORDER BY seq", (key,)).fetchall()
    return head, items


def qaqc_file_stem(key: str, title: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")
    return f"QAQC_{safe}_Checklist"


def _write_qaqc_docx(head, items: list, out_path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Inches

    doc = Document()
    for section in doc.sections:
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)

    doc.add_heading(head["title"], level=0)
    sub = doc.add_paragraph(f"{QAQC_SUBTITLE} (module Q{head['module_id'] - 100})")
    sub.runs[0].italic = True
    doc.add_paragraph(head["intro"])
    doc.add_paragraph("Location / area: ____________________   Cable or test ID: ____________________")

    sources: dict[str, str] = {}
    current = object()
    table = None
    for it in items:
        if it["section"] != current:
            current = it["section"]
            doc.add_heading(current, level=2)
            table = doc.add_table(rows=0, cols=3)
            table.style = "Table Grid"
            table.autofit = False
            # LibreOffice sizes columns from the table grid, not from the cell widths
            for col, w in zip(table.columns, (0.45, 5.5, 0.95)):
                col.width = Inches(w)
        n = sources.setdefault(it["source_url"], str(len(sources) + 1))
        row = table.add_row().cells
        row[0].width = Inches(0.45)
        row[1].width = Inches(5.5)
        row[2].width = Inches(0.95)
        row[0].text = "[ ]"
        row[1].text = it["text"]
        row[2].text = f"src {n}"
        for cell in row:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(9.5)
        row[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.add_paragraph()
    doc.add_paragraph("Inspected by: ____________________   Date: ____________   "
                      "Result:  [ ] Accept   [ ] Reject / NCR no. __________")
    doc.add_heading("Sources", level=2)
    labels = {it["source_url"]: it["source_label"] for it in items}
    for url, n in sources.items():
        p = doc.add_paragraph(f"src {n}: {labels[url]} - {url}")
        p.runs[0].font.size = Pt(8.5)
    foot = doc.add_paragraph(QAQC_FOOTER)
    foot.runs[0].font.size = Pt(8)
    foot.runs[0].italic = True
    doc.save(str(out_path))


def export_qaqc(con, key: str, out_dir: Path, pdf: bool = True) -> list[Path]:
    """Write one QA/QC checklist as Word (and PDF when LibreOffice is available)."""
    head, items = _qaqc_list(con, key)
    if head is None or not items:
        raise ValueError(f"no QA/QC checklist {key!r} (known: {', '.join(qaqc_keys(con)) or 'none'})")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / (qaqc_file_stem(key, head["title"]) + ".docx")
    _write_qaqc_docx(head, items, docx_path)
    written = [docx_path]
    if pdf:
        pdf_path = _to_pdf(docx_path, out_dir)
        if pdf_path is not None:
            written.append(pdf_path)
    return written


def export_qaqc_all(con, out_dir: Path, pdf: bool = True) -> list[Path]:
    written: list[Path] = []
    for key in qaqc_keys(con):
        written.extend(export_qaqc(con, key, out_dir, pdf=pdf))
    return written


def main(argv: list[str]) -> int:
    module_id: int | None = None
    want_all = False
    qaqc_key: str | None = None
    want_qaqc = False
    pdf = True
    out_dir = paths.ROOT / "exports"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--module", "-m") and i + 1 < len(argv):
            module_id = int(argv[i + 1]); i += 2; continue
        if a in ("--all", "-a"):
            want_all = True; i += 1; continue
        if a in ("--checklist", "-c") and i + 1 < len(argv):
            qaqc_key = argv[i + 1]; i += 2; continue
        if a == "--qaqc":
            want_qaqc = True; i += 1; continue
        if a == "--no-pdf":
            pdf = False; i += 1; continue
        if a in ("--out", "-o") and i + 1 < len(argv):
            out_dir = Path(argv[i + 1]).expanduser(); i += 2; continue
        if a in ("-h", "--help"):
            print(__doc__); return 0
        print(f"unknown argument: {a}"); return 2
    if module_id is None and qaqc_key is None and not want_qaqc:
        want_all = True

    if not paths.BANK_DB.exists():
        print("No question bank yet -- run './dashboard.sh build' first.")
        return 1
    con = db.bank_connect(paths.BANK_DB)
    try:
        if qaqc_key is not None or want_qaqc:
            if not qaqc_keys(con):
                print("This bank has no QA/QC checklists -- run './dashboard.sh qaqc build'.")
                return 1
        elif not has_checklists(con):
            print("This bank has no checklists -- run './dashboard.sh build' to add them.")
            return 1
        if pdf and soffice_path() is None:
            print("LibreOffice not found: writing Word files only.")
            pdf = False
        try:
            if qaqc_key is not None:
                written = export_qaqc(con, qaqc_key, out_dir, pdf)
            elif want_qaqc:
                written = export_qaqc_all(con, out_dir, pdf)
            else:
                written = export_all(con, out_dir, pdf) if want_all else export_module(con, module_id, out_dir, pdf)
        except ValueError as exc:
            print(exc); return 1
    finally:
        con.close()
    for p in written:
        print(p)
    return 0
