# OSHA 30 Dashboard — Build Plan

Written 2026-09-10; built the same day. Everything in this plan lives inside this
repository. No code, data, exports, or notes go anywhere else.

## Status

| Phase | Result |
|-------|--------|
| 0 Fence | done — own repository, secret-scan hooks armed and negative-tested |
| 1 Fact base | done — 1,540 page-grounded facts; question bank unchanged (0 id drift) |
| 2 Look Up | done — FTS5 search, `./dashboard.sh lookup`, four-door dashboard |
| 3 Inspect | done — 1,100 checklist items / 23 modules, Word + PDF export |
| 4 Interview | done — 56 deterministic scenarios (+ optional local-model narratives) |
| 5 Publish | done — README, screenshots, public repository |
| 6 QA/QC track | done 2026-11-20 — separate track (modules 101-106 = Q1-Q6), 185 grounded questions, 45-term EN/繁中 glossary, 35 key numbers, 5 checklists; OSHA rows verified identical |

The QA/QC track (phase 6) shares the scheduler and the four doors but not the content or
the scoring: `questions.track` / `facts.track` separate the two, OSHA modules stay 1-99 and
QA/QC modules 101-199 (enforced by a CHECK on the table), the mock exam and every OSHA number
read `track='osha'` only, and QA/QC streaks live in progress.db `track_streaks` (additive).
Grounding is on cached public web sources instead of the guide; see README.

## Ground rules

- One shared fact base. Every screen reads the same facts; no screen keeps its own copy.
- Each screen answers one kind of question (see the table). If a feature could fit two
  screens, it goes in the one whose question it answers, never both.
- The existing game (Train) is not modified beyond adding the new home menu.
- Every phase ends with a check you can run yourself, and nothing from a later phase
  starts until the check passes.

| Screen    | Question it answers                          | Scored? |
|-----------|----------------------------------------------|---------|
| Train     | Do I remember this one fact?                 | Yes     |
| Look Up   | What is the rule / number / regulation for X? | No      |
| Inspect   | Did I check everything for module N?         | No      |
| Interview | Can I explain what I would do in scenario X? | Self-rated only |

## Phase 0 — Fence the folder (half a day)

Right now this folder is not its own repository; it sits under a stale, oversized
version-control history that covers all of `~/GitHub`. Fix that first so nothing new
leaks out or mixes in.

1. Make this folder its own repository.
2. Add an ignore list: the virtual environment, Python caches, the extracted page cache,
   the personal progress database, and the exports folder.
3. First commit of what already exists (the game, the two PDFs, the certificate).

Check: a status command run inside the folder reports only this folder's files.

## Phase 1 — Fact base (1 day)

The game already mines terms, numbers, regulation references, and deadlines from the PDF
to build its 925 questions, but it only stores the questions. This phase stores the
facts themselves.

1. New table `facts` in the existing question-bank database: kind (term / threshold /
   cfr / deadline / sds), text, value, module, page, verbatim quote.
2. Fill it from the existing miners; no new PDF extraction, no AI.
3. Extend `./dashboard.sh build` to build both questions and facts.

Check: `./dashboard.sh status` prints fact counts per kind, and a spot-check of five
random facts against the PDF page they cite is correct.

## Phase 2 — Look Up (1–2 days)

1. Search: type a word or phrase, get matching facts ranked, each with the number,
   the regulation, and the page.
2. A command-line form, `./dashboard.sh lookup "guardrail height"`, for use from the
   phone over SSH or later through a Telegram bot.
3. A Look Up screen in the app, and the new four-door home menu (Train / Look Up /
   Inspect / Interview) replacing the current game-only home.

Check: ten common questions ("how many feet", "how many days to report") return the
right fact first.

## Phase 3 — Inspect (2 days)

1. Build one checklist per module from the fact base plus the guide's own "must /
   shall / required" sentences, each item carrying its page.
2. Inspect screen: pick a module, walk the checklist, tick items, jump to Look Up on
   any item.
3. Export the current checklist, or all 23, as Word and PDF into `exports/` inside
   this folder.

Check: export module 1 and open both files; every item has a page reference.

## Phase 4 — Interview (2 days)

1. Scenario bank: one scenario per lesson built from the module's facts, with a model
   answer quoting the guide. Optional AI-written extras use the existing Ollama / agy
   build-time backends with the same grounding check the game already uses.
2. Interview screen: read the scenario, think it through, reveal the model answer,
   rate yourself. Ratings go to a separate table and never touch the game's schedule.

Check: run through five scenarios end to end; ratings appear in stats.

## Phase 5 — Publish (1 day, last, separate from the app)

1. README with screenshots and a short write-up, same style as the threat-hunt
   write-ups.
2. Secret scan on the history before it goes public (there is a personal progress
   database and a certificate PDF in here; both stay ignored or are removed).
3. Push as its own public repository.

Check: fresh clone on another machine runs `./dashboard.sh` and plays.

## Where things live

```
OSHA 30 Cert./
  PLAN.md                  this file
  dashboard.sh             launcher (existing, gains lookup / export commands)
  osha_game/
    content/               miners and builders (existing; gains facts + checklists + scenarios)
    game/                  scoring rules (existing, untouched)
    lookup/                NEW search engine
    ui/screens/            existing game screens + NEW lookup / inspect / interview / home4
  data/
    bank.db                questions + NEW facts / checklists / scenarios tables
    progress.db            personal, ignored by version control
  exports/                 Word + PDF checklists, ignored by version control
```
