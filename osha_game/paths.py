"""Every path in the project, resolved from this file (space-safe, cwd-independent)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"
BANK_DB = DATA / "bank.db"
PROGRESS_DB = DATA / "progress.db"
CONFIG_TOML = ROOT / "config.toml"
GUIDE_PDF = ROOT / "OSHA - 30 Hours General Industry Outreach - Study Guide.pdf"
SDS_PDF = ROOT / "Sample SDS Handout.pdf"
CARDS_JSON = ROOT / "cards_data.json"
PAGES_GUIDE = CACHE / "pages_guide.jsonl"
PAGES_SDS = CACHE / "pages_sds.jsonl"
BUILD_REPORT = CACHE / "build_report.json"


def ensure_dirs() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
