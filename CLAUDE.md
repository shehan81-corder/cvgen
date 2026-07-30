# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CVGen: a small, personal, local web app that tailors a `.docx` CV (and
optionally a `.docx` cover letter) to a job description using the Claude
API, while structurally guaranteeing that dates, headers, titles, company
names, and contact info are never altered — and that fonts/colors/layout
are preserved exactly. Single user, no accounts, no database; everything
lives on local disk under `./data/session-<uuid>/` for the life of a
session. Full product spec: [`specs/spec.md`](specs/spec.md). Full
technical design: [`architecture.md`](architecture.md). Task breakdown
with build history and findings: [`tasks.md`](tasks.md).

## Commands

### Backend (FastAPI, Python)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # installs requirements.txt + pytest/httpx
cp .env.example .env   # then fill in ANTHROPIC_API_KEY — startup fails fast without it
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Run tests (from `backend/`):

```bash
.venv/bin/pytest -q                          # full suite
.venv/bin/pytest tests/test_classifier.py -v # single file
.venv/bin/pytest tests/test_classifier.py::test_name -v  # single test
```

`pytest.ini` sets `pythonpath = .`, so tests import as `app.*` / `tests.*`
without installing the package.

### Frontend (React 19 + Vite, TypeScript)

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, proxies /api/* to backend :8000 (see vite.config.ts)
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```

Both servers must be running for the app to work end to end. There is no
frontend test runner configured — verification is manual/browser-based
(see `tasks.md`'s F-series "Verify" sections) or via `npx tsc` for type
checking.

## Architecture: the two-stage pipeline

This is the one thing worth understanding before touching backend code —
it's why the codebase is shaped the way it is. Full rationale in
[`architecture.md`](architecture.md).

**The problem:** the spec requires that the LLM can *never* change dates,
job titles, company names, section headers, or contact info — and that
this be a structural guarantee, not a prompt instruction. It also wants
token cost minimized on every generate *and* retry.

**The solution — two stages:**

0. **Extraction — run-merging** (`app/services/docx_blocks.py`). Word
   commonly splits a single word or sentence across multiple runs (e.g.
   "TypeScript" saved as "Type" + "S" + "cript"). `_group_runs` merges
   adjacent same-style runs that don't cross a sentence boundary into one
   `Block` before anything downstream sees them, so the classifier and
   LLM operate on whole words/sentences, not arbitrary Word-internal run
   splits. A merged block's `BlockLocation.run_indices` records every
   original run it covers, since `docx_writer.py` still writes back
   per-run (into the first run of the group; the rest are cleared).

1. **Stage 0 — deterministic classifier, no LLM** (`app/services/classifier.py`).
   Runs once per upload. Walks the (merged) blocks and tags each one
   `editable` or `fixed` using paragraph styles + regexes (section
   headings, dates, emails, "Title, Company" shaped lines, etc.). CVs and
   cover letters use different default policies (`document_type="cv" |
   "cover_letter"`) — cover letters have no section headings to key off
   of, so they default to `editable` unless they look like a salutation/
   sign-off/short fragment. A heading candidate (short all-caps run) only
   counts if it's the first non-lowercase content in its paragraph —
   otherwise an inline acronym mid-bullet (e.g. "GCP") would be
   misdetected as a new section heading and silently freeze everything
   after it as `fixed` (this happened on a real CV; see `tasks.md`'s
   "Post-I1 fixes" entry). See architecture.md §4 for the full, ordered
   rule list and documented classifier limitations.

2. **Stage 1 — sparse-diff LLM call** (`app/services/llm_rewrite.py`).
   Only `editable` blocks (id + text, no style metadata) plus the job
   description are ever sent to Claude — `fixed` blocks are structurally
   never in the request, so the model cannot touch them even if it tried.
   The model returns *only* the blocks it changed
   (`[{id, text}, ...]`); anything omitted is treated as unchanged. CV and
   cover letter are rewritten in **one combined call** sharing a
   prompt-cached prefix (system prompt + editable blocks + job
   description), so retries are cheap — a retry re-sends the same cached
   prefix and pays only for the new sampling. Any returned `id` outside
   the `editable` set sent for that document is a hard validation
   failure (`InvalidEditIdsError`): the whole response is rejected, never
   partially applied.

Everything else wires around this: `app/services/docx_writer.py` applies
the sparse diff by writing new text into the *original* runs at their
original locations (never rebuilding document structure, so formatting
is inherently preserved) and builds the diff-preview JSON the frontend
renders. `app/services/ats_scoring.py` is an independent, deterministic
keyword-match service that scores *full* text (not just `editable`
blocks — a keyword can legitimately live in a `fixed` line); it excludes
a job description's perks/benefits section before extracting keywords,
since that content can never legitimately appear in a CV and would only
deflate the score.

### Request flow

```
frontend (React)
  -> POST /sessions/cv, /sessions/{id}/cover-letter   (app/routers/sessions.py)
       extract_blocks -> classify_blocks -> save as {cv,cover_letter}_blocks.json
  -> POST /sessions/{id}/job-description
  -> POST /sessions/{id}/generate | /retry             (app/routers/generation.py)
       loads job description + classified blocks -> generate_tailored_edits()
       (one combined LLM call) -> ats_scoring.match_score() for original/tailored
       -> persists sparse diff as draft_<n>.json -> returns preview JSON + ATS scores
  -> POST /sessions/{id}/accept                        (re-applies the exact reviewed
       draft_<n>.json via docx_writer — does NOT call the LLM again)
  -> GET  /sessions/{id}/download/{cv|cover-letter}
```

### Session storage

No database. `app/session.py` creates `./data/session-<uuid>/` per
session. `CVGEN_DATA_DIR` env var overrides the data root — tests use
this via the `client` fixture in `backend/tests/conftest.py` (each test
gets an isolated `tmp_path`, so tests never touch the real `./data/`).
Per session: `cv.docx`, `cover_letter.docx` (raw uploads),
`cv_blocks.json` / `cover_letter_blocks.json` (classified once at
upload, reused by every generate/retry), `draft_<n>.json` (one per
generate/retry call), `output/` (final accepted `.docx` files, named
`<original-name>-tailored-<job-slug>.docx`).

### Key invariant when touching this code

If you change `docx_blocks.py` (extraction), remember `classifier.py`
and `docx_writer.py` both consume its `Block`/`BlockLocation` output —
extraction changes ripple into both without those files needing edits,
*as long as the `Block` shape is preserved*, including `run_indices`
(the set of original runs a merged block covers — `docx_writer.py` needs
every one of them to write back correctly, not just `run_index`).

## Testing conventions

- `backend/tests/docx_fixtures.py` / `pdf_fixtures.py` build synthetic
  `.docx`/`.pdf` files in-memory for tests rather than checking in binary
  fixtures.
- `test_llm_rewrite.py` mocks the Anthropic client — no tests make real
  API calls (real end-to-end runs are done manually per `tasks.md`'s I1
  acceptance pass, not as part of the automated suite).
- When adding classifier test fixtures, prefer realistic/differently-
  formatted CV shapes (heading styles vs. all-caps markers, tables) over
  one canonical synthetic doc — `tasks.md`'s B3/I1 notes explain why
  (real-CV testing is what caught the two classifier bugs documented in
  architecture.md §4).
