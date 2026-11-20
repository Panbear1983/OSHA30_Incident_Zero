"""QA/QC track: the public source pages every QA/QC question, fact and checklist item cites.

The OSHA track grounds everything on a page of the study guide PDF. The QA/QC track has no
single book, so it grounds on a fixed list of free public web pages and PDFs (the reading
list of the 7-week pre-start program). `fetch()` downloads each one once, turns it into plain
text and caches it under data/cache/qaqc_sources/ (git-ignored, like the PDF page cache: it
is third-party material and is never committed). The grounding check in content/qaqc.py
then works exactly like validate.grounded(): a question is only accepted if its
`source_quote` is literally present (loose match) in the cached text of the source it cites.

  ./dashboard.sh qaqc fetch      download / refresh the cache (network, build-time only)

No client names, no project data: every source here is a generic public page.
"""
import hashlib
import html
import json
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .. import paths
from .norm import loose

CACHE_DIR = paths.CACHE / "qaqc_sources"
MANIFEST = CACHE_DIR / "manifest.json"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    label: str
    module_id: int     # 101..106, the QA/QC module this reading belongs to


SOURCES: tuple[Source, ...] = (
    # -- Q1 QA/QC fundamentals & documentation ---------------------------------------------
    # ASQ's "QA vs QC" page and Belden's J-hook blog are on the program's reading list but
    # answer automated fetches with HTTP 403: they stay listed (seed questions cite them) but
    # nothing can be grounded on them, so the build reports those seeds as ungrounded.
    Source("asq_qa_qc", "https://asq.org/quality-resources/quality-assurance-vs-control",
           "ASQ: Quality assurance vs quality control", 101),
    Source("procore_qsr", "https://learn.procore.com/quality-safety-and-risk",
           "Procore Learn: Quality, Safety & Risk", 101),
    Source("procore_cme", "https://learn.procore.com/construction-management-essentials-the-basics",
           "Procore Learn: Construction Management Essentials", 101),
    Source("procore_submittals", "https://learn.procore.com/intro-to-submittals",
           "Procore Learn: Intro to Submittals", 101),
    Source("hsm_cx_levels",
           "https://hsmuniversity.org/us/course/dce-450-commissioning-reliability-and-operations/"
           "lesson-2-commissioning-levels-test-scripts-and-documentation",
           "HSM University: Commissioning levels, test scripts and documentation", 101),
    # -- Q2 copper structured cabling & CCTV -----------------------------------------------
    Source("fluke_pl_channel",
           "https://www.flukenetworks.com/blog/cabling-chronicles/"
           "dumb-thing-1-specifying-channel-testing-when-installing-permanent-links",
           "Fluke Networks: channel vs permanent link testing", 102),
    Source("fluke_top10", "https://www.flukenetworks.com/blog/cabling-chronicles/top-10-cable-testing-mistakes",
           "Fluke Networks: top 10 cable testing mistakes", 102),
    Source("fluke_marginal",
           "https://www.flukenetworks.com/knowledge-base/dsx-cableanalyzer-series/marginal-bands-dsx-cableanalyzer",
           "Fluke Networks: marginal (*) results on the DSX CableAnalyzer", 102),
    Source("c3_install", "https://3c3.com/structured-cabling-installation",
           "3C3: structured cabling installation limits", 102),
    Source("brady_606", "https://bradyid.com/resources/tia-606-c-cable-labeling-standards",
           "Brady: TIA-606-C cable labeling standards", 102),
    Source("belden_jhooks",
           "https://belden.com/blog/installing-j-hooks-avoid-these-mistakes-to-maintain-network-uptime",
           "Belden: installing J-hooks", 102),
    Source("cabletakeoff_jhooks", "https://cabletakeoff.com/blog/j-hook-spacing-and-fill-tia-569-bicsi",
           "Cable Takeoff: J-hook spacing and fill (TIA-569 / BICSI)", 102),
    Source("ifc_firestop",
           "https://firestop.org/wp-content/uploads/2025/04/IFC-Firestop-Pocket-Inspection-Guide-6th-edition-2025.pdf",
           "IFC: Firestop Pocket Inspection Guide (6th ed.)", 102),
    Source("axis_quality", "https://whitepapers.axis.com/en-us/quality-with-a-purpose",
           "Axis: image quality with a purpose", 102),
    # -- Q3 fiber optics --------------------------------------------------------------------
    Source("foa_quickstart_test", "https://foa.org/tech/ref/quickstart/test.html",
           "FOA QuickStart: fiber optic testing", 103),
    Source("foa_loss_est", "https://thefoa.org/tech/loss-est.htm",
           "FOA: what loss to expect (loss budget)", 103),
    Source("foa_5ways", "https://www.thefoa.org/tech/ref/testing/5ways/fiveways.html",
           "FOA: five ways to test fiber", 103),
    Source("foa_refcables", "https://www.foa.org/tech/ref/testing/Instruments/refcables.html",
           "FOA: reference cables", 103),
    Source("foa_scope", "https://www.thefoa.org/tech/ref/testing/test/scope.html",
           "FOA: connector inspection and cleaning", 103),
    Source("foa_8", "https://foa.org/tech/ref/1pstandards/FOA-8.pdf",
           "FOA-8 standard: inspecting and cleaning connectors", 103),
    Source("fluke_endface",
           "https://www.flukenetworks.com/blog/cabling-chronicles/easier-fiber-end-face-inspection",
           "Fluke Networks: fiber end-face inspection zones", 103),
    Source("foa_installcbl", "https://foa.org/tech/ref/install/installcbl.html",
           "FOA: installing fiber optic cable", 103),
    Source("foa_otdr", "https://www.thefoa.org/tech/ref/testing/OTDR/OTDR.html",
           "FOA: OTDR testing", 103),
    Source("fluke_tiers", "https://www.flukenetworks.com/blog/cabling-chronicles/tips-taking-top-tier-fiber-testing",
           "Fluke Networks: Tier 1 vs Tier 2 fiber testing", 103),
    Source("tiafotc_5683e", "https://www.tiafotc.org/tia-standards-update/tia-568-3-e/",
           "TIA FOTC: TIA-568.3-E update", 103),
    Source("gtfiber_polarity",
           "https://www.gtfiber.us/blogs/fiber-knowledge/tia-568-3-e-mpo-polarity-methods-a-b-c-u1-u2",
           "GT Fiber: TIA-568.3-E MPO polarity methods", 103),
    # -- Q4 power cable pulling & testing ---------------------------------------------------
    Source("southwire_guide", "https://m.media-amazon.com/images/I/B10tU0dZhBS.pdf",
           "Southwire: Power Cable Installation Guide", 104),
    Source("hre_nec392", "https://hreconstruction.com/blogs/f/cable-tray-installation-what-nec-392-requires",
           "HRE: cable tray installation, what NEC 392 requires", 104),
    Source("megger_stitch", "https://testequipmentdepot.com/media/pdfs/electrical-insulation-testing_guide.pdf",
           "Megger: A Stitch in Time (insulation testing guide)", 104),
    Source("nema_torque",
           "https://nema.org/docs/default-source/technical-document-library/"
           "using-torque-tools-for-terminating-building-wire4820b20b-e723-4f1d-8863-a491a1fd6f4d.pdf?sfvrsn=b4e9097c_3",
           "NEMA Bulletin 120: torque tools for terminating building wire", 104),
    # -- Q5 electrical safety + FMCS + tools ------------------------------------------------
    Source("osha_1910_147", "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147",
           "OSHA 29 CFR 1910.147: control of hazardous energy", 105),
    Source("osha_4472", "https://www.osha.gov/sites/default/files/publications/OSHA4472.pdf",
           "OSHA 4472: arc flash fact sheet", 105),
    Source("vt_boundaries",
           "https://ehs.vt.edu/programs/occupational-safety/electrical-safety/approach-boundaries.html",
           "Virginia Tech EHS: electrical approach boundaries", 105),
    Source("uconn_70e",
           "https://ehs.media.uconn.edu/wp-content/uploads/sites/3238/2025/04/2024-NFPA-70E-Tables-Accessible-1.pdf",
           "UConn EHS: NFPA 70E-2024 tables", 105),
    Source("osha_3842", "https://www.osha.gov/sites/default/files/publications/OSHA3842.pdf",
           "OSHA 3842: scissor lift safety", 105),
    Source("facilityos_fmcs", "https://www.facilitysystem.com/en/solutions/semiconductor/",
           "FacilityOS: FMCS for semiconductor fabs", 105),
    # -- Q6 site readiness (cleanroom, heat, onboarding) ------------------------------------
    Source("nycreates_cleanroom",
           "https://ny-creates.org/wp-content/uploads/OPS-00001-R26-Cleanroom-Protocol-Requirements.pdf",
           "NY CREATES: cleanroom protocol requirements", 106),
    Source("osha_heat", "https://www.osha.gov/heat-exposure",
           "OSHA: heat exposure", 106),
    Source("osha_heat_water", "https://www.osha.gov/heat-exposure/water-rest-shade",
           "OSHA: water, rest, shade", 106),
    Source("osha_heat_new", "https://www.osha.gov/heat-exposure/protecting-new-workers",
           "OSHA: protecting new workers from heat", 106),
    Source("osha_outreach", "https://www.osha.gov/training/outreach",
           "OSHA: Outreach Training Program (10- and 30-hour)", 106),
)

BY_KEY = {s.key: s for s in SOURCES}


# -- HTML / PDF -> text ------------------------------------------------------------------

class _Text(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "template", "iframe"}
    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4",
              "h5", "h6", "section", "article", "table", "dd", "dt", "blockquote", "pre",
              "header", "footer", "nav", "main", "aside", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    text = html.unescape("".join(p.out))
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def pdf_to_text(data: bytes) -> str:
    import fitz  # build-time only, same dependency the OSHA page extractor uses
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text("text") for page in doc)


def _download(url: str, timeout: int = 60) -> tuple[bytes, str]:
    """curl first (it uses the system trust store; the python.org framework build of Python
    ships without CA certificates until 'Install Certificates.command' is run), urllib as
    the fallback where curl is missing."""
    curl = shutil.which("curl")
    if curl:
        with tempfile.TemporaryDirectory(prefix="qaqc_fetch_") as tmp:
            body = Path(tmp) / "body"
            proc = subprocess.run(
                [curl, "-sSL", "--compressed", "--max-time", str(timeout), "-A", _UA,
                 "-H", "Accept-Language: en-US,en;q=0.9",
                 "-H", "Accept: text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
                 "-o", str(body), "-w", "%{http_code} %{content_type}", url],
                capture_output=True, text=True, timeout=timeout + 15,
            )
            if proc.returncode != 0:
                raise OSError(f"curl exit {proc.returncode}: {proc.stderr.strip()[:80]}")
            code, _, ctype = proc.stdout.strip().partition(" ")
            if not code.startswith("2"):
                raise OSError(f"HTTP {code}")
            return body.read_bytes(), ctype
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read(), (resp.headers.get("Content-Type") or "")


def cache_path(key: str):
    return CACHE_DIR / f"{key}.txt"


def fetch(keys: list[str] | None = None, force: bool = False, log=print) -> dict:
    """Download every source (or `keys`) into the cache. Returns {key: status}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    status: dict[str, str] = {}
    for src in SOURCES:
        if keys and src.key not in keys:
            continue
        out = cache_path(src.key)
        if out.exists() and not force:
            status[src.key] = "cached"
            continue
        try:
            data, ctype = _download(src.url)
            if data[:5] == b"%PDF-" or "pdf" in ctype.lower():
                text = pdf_to_text(data)
            else:
                text = html_to_text(data.decode("utf-8", errors="replace"))
        except Exception as exc:  # network / HTTP / parse: recorded, never fatal
            status[src.key] = f"error: {exc.__class__.__name__}: {str(exc)[:80]}"
            log(f"  {src.key:<22} {status[src.key]}")
            continue
        if len(text) < 300:
            status[src.key] = f"error: only {len(text)} chars of text"
            log(f"  {src.key:<22} {status[src.key]}")
            continue
        out.write_text(text, encoding="utf-8")
        manifest[src.key] = {
            "url": src.url, "chars": len(text),
            "sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        status[src.key] = f"ok {len(text)} chars"
        log(f"  {src.key:<22} {status[src.key]}")
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    return status


def have_cache() -> bool:
    return CACHE_DIR.exists() and any(cache_path(s.key).exists() for s in SOURCES)


def loose_texts() -> dict[str, str]:
    """{source key: loose-normalized cached text} for every source that is cached."""
    out = {}
    for s in SOURCES:
        p = cache_path(s.key)
        if p.exists():
            out[s.key] = loose(p.read_text(encoding="utf-8"))
    return out


def grounded(quote: str, source_key: str, texts: dict[str, str]) -> bool:
    """Same rule as validate.grounded(): the (loose-normalized) quote, capped at 400 chars,
    must appear literally in the cited source's text."""
    if not quote or source_key not in texts:
        return False
    needle = loose(quote)[:400]
    return bool(needle) and needle in texts[source_key]
