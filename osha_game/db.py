"""Two SQLite files: bank.db (rebuildable question bank) and progress.db (sacred player data).

The game opens progress.db and ATTACHes bank.db as `bank`.
Build code only ever gets a bank connection — it has no path to progress.db by construction.
"""
import sqlite3
from pathlib import Path
from . import paths

BANK_DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS modules(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  topic TEXT NOT NULL,
  page_start INTEGER NOT NULL, page_end INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY,
  module_id INTEGER NOT NULL REFERENCES modules(id),
  label TEXT NOT NULL,
  page_start INTEGER NOT NULL, page_end INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS questions(
  qid TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('mc','blank')),
  category TEXT NOT NULL,
  module_id INTEGER REFERENCES modules(id),
  lesson_id INTEGER REFERENCES lessons(id),
  prompt TEXT NOT NULL,
  correct TEXT NOT NULL,
  options TEXT NOT NULL,
  explanation TEXT,
  cfr TEXT,
  page INTEGER,
  source_doc TEXT NOT NULL DEFAULT 'guide' CHECK(source_doc IN ('guide','sds')),
  source_quote TEXT,
  origin TEXT NOT NULL CHECK(origin IN ('deterministic','ollama','gemini','imported')));
CREATE INDEX IF NOT EXISTS idx_q_module ON questions(module_id);
CREATE INDEX IF NOT EXISTS idx_q_cat ON questions(category);
"""

PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS profiles(
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL COLLATE NOCASE,
  created_at TEXT NOT NULL, last_seen_at TEXT,
  days_without_incident INTEGER NOT NULL DEFAULT 0,
  best_streak INTEGER NOT NULL DEFAULT 0,
  lifetime_score INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS srs(
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  qid TEXT NOT NULL,
  due TEXT NOT NULL,
  state INTEGER, stability REAL, difficulty REAL, last_review TEXT,
  reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
  card_json TEXT NOT NULL,
  PRIMARY KEY(profile_id, qid));
CREATE INDEX IF NOT EXISTS idx_srs_due ON srs(profile_id, due);
CREATE TABLE IF NOT EXISTS shifts(
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  module_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT,
  questions INTEGER, correct INTEGER, near_misses INTEGER, incidents INTEGER,
  score INTEGER,
  outcome TEXT CHECK(outcome IN ('clean','incident','abandoned')));
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  shift_id INTEGER REFERENCES shifts(id),
  exam_id INTEGER,
  qid TEXT NOT NULL,
  at TEXT NOT NULL,
  chosen TEXT,
  result TEXT NOT NULL CHECK(result IN ('hit','near_miss','incident')),
  bet INTEGER NOT NULL DEFAULT 0,
  ms INTEGER);
CREATE TABLE IF NOT EXISTS exams(
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  at TEXT NOT NULL, duration_s INTEGER,
  total INTEGER, correct INTEGER, passed INTEGER NOT NULL,
  detail TEXT);
"""


def _pragmas(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA synchronous=NORMAL")


def bank_connect(path: Path | None = None, create: bool = False) -> sqlite3.Connection:
    """Bank-only connection — the ONLY helper build code may use."""
    path = path or paths.BANK_DB
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    _pragmas(con)
    if create:
        con.executescript(BANK_DDL)
    return con


def game_connect() -> sqlite3.Connection:
    """Progress connection with the bank attached read-alongside as `bank`."""
    paths.ensure_dirs()
    con = sqlite3.connect(paths.PROGRESS_DB)
    con.row_factory = sqlite3.Row
    _pragmas(con)
    con.executescript(PROGRESS_DDL)
    con.execute("ATTACH DATABASE ? AS bank", (str(paths.BANK_DB),))
    return con
