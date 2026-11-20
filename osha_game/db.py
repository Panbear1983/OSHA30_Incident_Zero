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
  -- OSHA track: modules(id) 1-23.  QA/QC track: qaqc_modules(id) 101-106.  (Two possible
  -- parents, so no REFERENCES clause; the CHECK at the bottom keeps the ranges apart.)
  module_id INTEGER,
  lesson_id INTEGER REFERENCES lessons(id),
  prompt TEXT NOT NULL,
  correct TEXT NOT NULL,
  options TEXT NOT NULL,
  explanation TEXT,
  cfr TEXT,
  page INTEGER,
  source_doc TEXT NOT NULL DEFAULT 'guide' CHECK(source_doc IN ('guide','sds','qaqc')),
  source_quote TEXT,
  origin TEXT NOT NULL CHECK(origin IN ('deterministic','ollama','gemini','imported','claude')),
  track TEXT NOT NULL DEFAULT 'osha' CHECK(track IN ('osha','qaqc')),
  source_url TEXT,
  source_label TEXT,
  CHECK ((track = 'osha' AND source_doc IN ('guide','sds') AND (module_id IS NULL OR module_id BETWEEN 1 AND 99))
      OR (track = 'qaqc' AND source_doc = 'qaqc' AND module_id BETWEEN 101 AND 199
          AND length(coalesce(source_url, '')) > 0 AND length(coalesce(source_label, '')) > 0)));
CREATE INDEX IF NOT EXISTS idx_q_module ON questions(module_id);
CREATE INDEX IF NOT EXISTS idx_q_cat ON questions(category);
CREATE INDEX IF NOT EXISTS idx_q_track ON questions(track);
-- Shared fact base (Look Up / Inspect / Interview all read this; none of them mine the PDF).
-- QA/QC facts (glossary terms with a Traditional Chinese name, key numbers) cite a public
-- source page instead of a guide page: page = 0, source_url / source_label set.
CREATE TABLE IF NOT EXISTS facts(
  fid TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('term','threshold','deadline','cfr','rule','sds')),
  subject TEXT NOT NULL,
  value TEXT NOT NULL,
  quote TEXT NOT NULL,
  page INTEGER NOT NULL,
  module_id INTEGER,
  lesson_id INTEGER REFERENCES lessons(id),
  cfr TEXT,
  number REAL,
  unit TEXT,
  source_doc TEXT NOT NULL DEFAULT 'guide' CHECK(source_doc IN ('guide','sds','qaqc')),
  track TEXT NOT NULL DEFAULT 'osha' CHECK(track IN ('osha','qaqc')),
  source_url TEXT,
  source_label TEXT,
  zh TEXT,
  CHECK ((track = 'osha' AND source_doc IN ('guide','sds'))
      OR (track = 'qaqc' AND source_doc = 'qaqc' AND length(coalesce(source_url, '')) > 0)));
CREATE INDEX IF NOT EXISTS idx_f_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_f_module ON facts(module_id);
CREATE INDEX IF NOT EXISTS idx_f_track ON facts(track);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
  subject, value, quote, fid UNINDEXED, tokenize='porter unicode61');
-- Inspect: one ordered checklist per module, built from 'rule' facts at build time.
CREATE TABLE IF NOT EXISTS checklist_items(
  cid TEXT PRIMARY KEY,
  module_id INTEGER NOT NULL REFERENCES modules(id),
  lesson_id INTEGER REFERENCES lessons(id),
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  page INTEGER NOT NULL,
  cfr TEXT,
  fid TEXT REFERENCES facts(fid));
CREATE INDEX IF NOT EXISTS idx_c_module ON checklist_items(module_id, seq);
-- Interview: one scenario per lesson with a model answer assembled from facts.
CREATE TABLE IF NOT EXISTS scenarios(
  sid TEXT PRIMARY KEY,
  module_id INTEGER NOT NULL REFERENCES modules(id),
  lesson_id INTEGER REFERENCES lessons(id),
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  answer_json TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'deterministic' CHECK(origin IN ('deterministic','ollama')));
CREATE INDEX IF NOT EXISTS idx_s_module ON scenarios(module_id);
-- QA/QC track (separate from the OSHA course: own modules, own checklists, own sources).
CREATE TABLE IF NOT EXISTS qaqc_modules(
  id INTEGER PRIMARY KEY CHECK(id BETWEEN 101 AND 199),
  week INTEGER NOT NULL,
  title TEXT NOT NULL,
  topic TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qaqc_checklists(
  key TEXT PRIMARY KEY,
  module_id INTEGER NOT NULL REFERENCES qaqc_modules(id),
  seq INTEGER NOT NULL,
  title TEXT NOT NULL,
  intro TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qaqc_checklist_items(
  cid TEXT PRIMARY KEY,
  list_key TEXT NOT NULL REFERENCES qaqc_checklists(key),
  seq INTEGER NOT NULL,
  section TEXT NOT NULL,
  text TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_label TEXT NOT NULL,
  quote TEXT);
CREATE INDEX IF NOT EXISTS idx_qci_list ON qaqc_checklist_items(list_key, seq);
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
-- Inspect ticks and Interview self-ratings live here (per profile), never in bank.db.
CREATE TABLE IF NOT EXISTS checklist_ticks(
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  cid TEXT NOT NULL,
  ticked_at TEXT NOT NULL,
  PRIMARY KEY(profile_id, cid));
CREATE TABLE IF NOT EXISTS interview_ratings(
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  sid TEXT NOT NULL,
  rating INTEGER NOT NULL CHECK(rating IN (1,2,3)),
  at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ir_profile ON interview_ratings(profile_id, at);
-- Per-track streak for tracks other than OSHA (added with the QA/QC track; additive only).
-- The OSHA streak stays in profiles.days_without_incident / best_streak / lifetime_score,
-- so a QA/QC shift can never move an OSHA number.
CREATE TABLE IF NOT EXISTS track_streaks(
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  track TEXT NOT NULL,
  days_without_incident INTEGER NOT NULL DEFAULT 0,
  best_streak INTEGER NOT NULL DEFAULT 0,
  lifetime_score INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(profile_id, track));
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
