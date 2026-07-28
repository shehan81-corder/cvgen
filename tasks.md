# CVGen — Implementation Tasks

Derived from [`specs/spec.md`](specs/spec.md) and
[`architecture.md`](architecture.md) (Option B: two-stage pipeline —
deterministic block classifier + sparse-diff LLM call). Each task is
scoped to fit in a single Claude Code session and produces a testable
slice. Tasks are grouped by layer; dependencies are listed explicitly so
they can be tackled in order (or in parallel where independent).

---

## B1 — Project scaffolding

**Spec refs:** spec §4 (Tech stack), architecture §2 (component overview)

**Scope:** Backend (FastAPI) + Frontend (React/Vite) skeletons, wired
together for local dev. No feature logic yet.

- FastAPI app with a `/health` endpoint.
- `.env` loading for `ANTHROPIC_API_KEY` at startup; fail fast with a clear
  message if missing.
- React + Vite app skeleton, dev server proxying API calls to the backend.
- `./data/session-<uuid>/` working-directory convention created but unused
  (no session logic yet — just the directory helper).
- Run scripts / README notes for starting both servers locally.

**Depends on:** nothing (first task).

**Verify:**
- `uvicorn` starts and `/health` returns 200.
- Backend exits with a clear error if `.env` lacks `ANTHROPIC_API_KEY`.
- `npm run dev` (or equivalent) serves the frontend and it can reach
  `/health` through the dev proxy.

---

## B2 — Docx block extraction module

**Spec refs:** spec §7.1; architecture §3 (block model)

**Scope:** Backend, pure library code (no HTTP layer, no classification
yet). Shared by CV and cover letter processing.

- Given a `.docx` path, walk paragraphs (and table cells) and emit a list
  of "blocks" — each with a stable block ID, its text, its location
  (paragraph index / table+cell+paragraph index, run index), and its
  paragraph style name (e.g. `Heading1`, `Normal`, `ListParagraph`) —
  the style name is needed by B3's classifier.
- Extract per-run style metadata needed for spec §8 preview: font family,
  size, color, bold/italic/underline.
- Don't crash on tables; extract their text as blocks too (see spec §13).

**Depends on:** B1.

**Verify:**
- Unit tests against 2-3 sample `.docx` fixtures (plain paragraphs, bullet
  lists, at least one with a table) confirm: every visible text run is
  captured as a block, block IDs are stable across repeated calls on the
  same file, paragraph style names are captured accurately, and style
  metadata matches what's actually set in the sample files.

---

## B3 — Block classifier (stage 0: editable vs. fixed)

**Spec refs:** architecture §4 (full ruleset)

**Scope:** Backend, pure library code, no LLM involved. New component
introduced by the two-stage design.

- Implement the rule-based classifier from architecture §4: section
  detection via heading styles / all-caps short lines against a known
  section-alias list; fixed-pattern detection (email/phone/URL, date
  patterns, "Title, Company" / "Degree, Institution" shaped lines);
  section-based default (`experience`/`summary`/`skills`/`projects` →
  `editable`; `education`/`certifications`/`contact`/unrecognized →
  `fixed`, conservative default).
- Annotate each block from B2 with `section` and `editable: true|false`.

**Depends on:** B2.

**Verify:**
- Unit tests against several real-shaped CV fixtures (differently
  formatted — at least one with heading styles, one using bold/all-caps
  section markers instead of heading styles) confirm: dates, contact
  info, job titles, company names, and section headers are always
  classified `fixed`; a representative sample of experience/summary/
  skills bullets are classified `editable`.
- Explicit "known gap" test: document a case where classification is
  expected to be conservative (e.g. an oddly-styled bullet falling back
  to `fixed`) so the behavior is intentional and asserted, not accidental.
- This task's fixtures should be reused later in I1 as the multi-template
  acceptance set.

---

## B4 — Upload endpoints, validation & session storage

**Spec refs:** spec §5.1, §5.2; architecture §9 (session storage
additions)

**Scope:** Backend HTTP layer.

- `POST` endpoints to upload CV and (optionally) cover letter `.docx`
  files into a new session working directory.
- Enforce: `.docx` only (reject others with the exact error text from
  spec §5.2), file size cap (10 MB), parse-on-upload via B2 — reject
  corrupt/unsupported files immediately with a clear error.
- On successful parse, run B3's classifier and persist the annotated
  block list as `cv_blocks.json` / `cover_letter_blocks.json` in the
  session directory (architecture §9) — classification happens once here,
  not on every generate/retry.
- Session ID issuance and the `./data/session-<uuid>/` directory
  lifecycle.

**Depends on:** B1, B2, B3.

**Verify:**
- Upload a valid CV `.docx` → 200, session ID returned, `cv_blocks.json`
  exists with `section`/`editable` populated on every block.
- Upload a `.pdf` as CV → rejected with the specified error message, no
  file persisted.
- Upload a corrupted/password-protected `.docx` → rejected with a clear
  parse error.
- Upload an 11 MB file → rejected for size.
- Cover letter upload is optional — a session with only a CV is valid.

---

## B5 — Job description ingestion

**Spec refs:** spec §5.1 (job description row)

**Scope:** Backend HTTP layer + small text-extraction utility.

- Endpoint accepting either pasted text or an uploaded `.docx`/`.pdf` for
  the job description, normalizing to plain text stored against the
  session.
- PDF/docx text extraction (formatting irrelevant here per spec — text
  only).

**Depends on:** B1, B4 (shares session concept).

**Verify:**
- Pasted text is stored and retrievable as-is.
- Uploaded `.docx` job description extracts to equivalent plain text.
- Uploaded `.pdf` job description extracts readable text (spot-check
  against a sample PDF with known content).
- Missing job description on a session → generation request (B7) is
  rejected with a clear 400 reason.

---

## B6 — LLM rewrite service (stage 1: sparse diff, combined call)

**Spec refs:** spec §7.2, §7.3, §7.4; architecture §5 (full contract)

**Scope:** Backend, service layer. Single service covering CV and cover
letter together in one call.

- Build the combined prompt: one system prompt encoding spec §7.2's rules
  plus the sparse-output contract; user content includes the job
  description plus the CV's `editable` blocks (id + text only, no style
  metadata) and, if present, the cover letter's `editable` blocks,
  clearly separated per architecture §5.
- Call the Claude API with the static prefix (system prompt + editable
  blocks + job description) as a cached prompt segment.
- Parse the sparse response: `[{id, text}, ...]` per document. Validate
  every returned `id` is a member of the `editable` set that was sent for
  that document — any id outside that set is a hard validation failure
  (reject the whole response, typed retryable error, never partially
  apply).
- A response that changes zero blocks across both documents is valid but
  flagged as low-confidence (surfaced to the caller, not swallowed).
- Retry = re-invoke this service with identical inputs; no special retry
  code path needed beyond "call again."

**Depends on:** B1, B4 (consumes its classified block format).

**Verify:**
- Unit test with a mocked Claude response containing only valid,
  in-scope ids → returns parsed sparse changes correctly; blocks not
  present in the response are confirmed treated as unchanged by the
  caller.
- Unit test with a mocked response containing an id outside the sent
  `editable` set → service raises the validation error, no partial data
  returned.
- Unit test with a mocked empty-changes response → treated as valid but
  flagged low-confidence, not an error.
- Manual/integration test with a real sample CV + job description +
  cover letter in one call: confirm both documents' changes come back
  correctly attributed, no `fixed`-classified content appears in the
  response (it was never sent, so this should be structurally
  impossible — assert it anyway), and no fabricated skills/claims appear.
- Buzzword smoke test: grep model output against a small denylist (from
  spec §7.2: "synergize", "leverage", "spearheaded", "results-driven",
  "dynamic", "cutting-edge").
- Cost/latency spot check: confirm a second call (retry) against the same
  session is measurably cheaper/faster than the first (cache hit),
  logging token usage from the API response.

---

## B7 — Docx writer & diff-preview builder

**Spec refs:** spec §7.1 (write-back), §8 (preview JSON), §10 (output
files); architecture §6

**Scope:** Backend, service layer.

- Given a document's classified block list (B4) + B6's sparse diff for
  that document, start from "all blocks unchanged" and apply only the
  returned changes into the *existing* runs at their original locations
  (text only — formatting untouched); save as a new `.docx`.
- Build the preview JSON described in spec §8 / architecture §6: per
  block, text (original + tailored) + style metadata + `section` +
  `editable` + changed/unchanged flag, so the frontend can distinguish
  "not eligible for editing" (`fixed`) from "eligible but left alone"
  (`editable`, unchanged) from "changed."
- Filename convention per spec §10:
  `<original-name>-tailored-<job-company-or-role-slug>.docx`.

**Depends on:** B4, B6.

**Verify:**
- Round-trip test: run an empty sparse diff (no changes) through the
  writer, confirm the output file is visually/structurally identical to
  the input.
- Apply a synthetic sparse diff changing one `editable` block, confirm
  only that block's text changed in the output file and its original run
  formatting (font/size/color/bold) is preserved, and that no `fixed`
  block could have been altered (assert by construction — the diff
  applier has no code path that touches `fixed` block ids).
- Preview JSON correctly labels `fixed`, `editable`-unchanged, and
  `editable`-changed blocks distinctly, matching what was actually
  written.
- Filename generated matches spec §10's naming convention given a sample
  job description.

---

## B8 — ATS match scoring service

**Spec refs:** spec §9; architecture §8 (confirms full-text scope)

**Scope:** Backend, service layer (independent of the LLM pipeline;
scores full document text, not just `editable` blocks — a keyword can
legitimately live in a `fixed` line).

- Extract candidate keywords/phrases from job description text.
- Compute match percentage against a given CV's full text (case-
  insensitive, basic stemming/lemmatization for plural/verb forms).
- Return a comparable score for both original and tailored CV text.

**Depends on:** B1 only (can be built in parallel with B2–B7).

**Verify:**
- Unit tests: a CV containing all extracted JD keywords scores ~100%; a
  CV containing none scores ~0%; plural/verb-form variants (e.g. "manage"
  vs "managed") still count as matches.
- Given a fixed JD + original/tailored CV pair, tailored score is higher
  than original when tailored text objectively contains more JD keywords.
- Confirm a keyword present only in a `fixed`-classified block (e.g. a
  tool name in a job title) still counts toward the score — scoring must
  not be scoped to `editable` blocks only.

---

## B9 — Generation orchestration API (CV + cover letter, combined)

**Spec refs:** spec §6 (steps 2–4), §10, §11; architecture §5, §9

**Scope:** Backend HTTP layer — wires B4/B5/B6/B7/B8 together into the
actual endpoints the frontend calls. Handles CV and cover letter together
in a single generate/retry cycle per architecture §5's combined-call
design; cover letter parts are simply absent from requests/responses when
no template was uploaded.

- `POST /sessions/{id}/generate` — invokes B6 once (covering CV + cover
  letter if present) then B7 + B8 for each document, returns diff-preview
  JSON and ATS scores for both. Persists the draft as `draft_<n>.json`
  (architecture §9) but does not yet write a final output file.
- `POST /sessions/{id}/retry` — same as generate, re-invokes B6 fresh per
  spec §7.4, creates a new `draft_<n>.json`.
- `POST /sessions/{id}/accept` — applies the specific draft the user
  reviewed (from its persisted `draft_<n>.json`, not a fresh LLM call) via
  B7's real file-writing path for each document present; returns download
  handles.
- `GET /sessions/{id}/download/{cv|cover-letter}` — serves the finalized
  file.
- Error handling per spec §11: missing JD blocks generate with 400; LLM
  failure surfaces as a retryable error without discarding session
  uploads; out-of-scope block id from B6 surfaces as a distinct error
  type.

**Depends on:** B4, B5, B6, B7, B8.

**Verify:**
- Full happy-path integration test, CV + cover letter + JD: generate →
  preview JSON has expected shape (both documents, `fixed`/`editable`
  labels, ATS scores) → accept → download both files, confirm unedited
  runs match the originals byte-for-byte in formatting.
- Same happy path with CV only (no cover letter) → generate/accept/
  download works identically for the CV, no cover letter fields present
  or erroring in the response.
- Retry twice on the same session → two independent `draft_<n>.json`
  files created, B6 genuinely invoked again (not cached/reused).
- Accept uses the exact reviewed draft, not a new generation — verify by
  asserting B6 is not called during `/accept`.
- Generate without a JD present → 400 with clear message, no partial
  session state corrupted.
- Simulate an LLM error → endpoint returns an error response; a
  subsequent retry on the same session still works (uploads weren't
  lost).

---

## F1 — Frontend upload screen

**Spec refs:** spec §6 (step 1), §5.2 (validation UX)

**Scope:** Frontend only, talks to B4/B5's endpoints.

- Upload screen: CV upload (required), cover letter upload (optional), job
  description as paste-text or file upload (required).
- Client-side pre-check (extension) plus surfacing server-side validation
  errors verbatim (wrong format, corrupt file, oversized file) inline next
  to the relevant field.
- Disables/guards proceeding to generate until required fields are valid.

**Depends on:** B4, B5.

**Verify:**
- Manual run: uploading a valid CV + pasted JD enables proceeding;
  uploading a PDF as CV shows the exact rejection message from spec §5.2;
  omitting the JD blocks progression with an inline message.
- Cover letter is clearly optional in the UI and skipping it doesn't block
  progress.

---

## F2 — Generate/Retry flow (loading & error states)

**Spec refs:** spec §6 (step 2), §11 (LLM failure UX)

**Scope:** Frontend, talks to B9's `generate`/`retry` endpoints.

- Trigger generation from the upload screen; loading state while backend
  call(s) run.
- On success, transition to the review screen (F3/F4) with the returned
  preview data.
- On LLM/backend failure, show an error state with a retry action per
  spec §11, without losing the user's uploaded inputs (i.e. don't force
  re-upload).

**Depends on:** F1, B9.

**Verify:**
- Manual run against a real backend: generate shows a loading indicator,
  then transitions to review on success.
- Force a backend error (e.g. temporarily bad API key) → UI shows a
  retry-capable error state, and retrying after fixing the issue succeeds
  without re-uploading files.

---

## F3 — Side-by-side rendered preview

**Spec refs:** spec §8; architecture §6

**Scope:** Frontend, rendering component consuming B7/B9's preview JSON.

- Renders original (left) vs tailored (right) documents from the
  block+style JSON — real font family/size/color/bold/italic/underline
  applied per block, not raw text.
- Highlights changed (`editable`) blocks on the tailored side; unchanged
  `editable` blocks render plainly on both sides; `fixed` blocks render
  visibly muted/labeled "not eligible for editing" per architecture §6 —
  this is the UI's way of surfacing classifier gaps to the user.
- Same component reused for the cover letter preview when present.

**Depends on:** F2, B7, B9.

**Verify:**
- Manual visual check against a real generated session: changed blocks
  are visibly highlighted only on the right; `fixed` blocks are visually
  distinct from `editable`-unchanged blocks (not just "no highlight" for
  both — a user must be able to tell "the model chose not to touch this"
  apart from "this was never a candidate"); font/size/color differences
  between blocks in the source document are visibly reflected; cover
  letter preview renders when present, absent when not.

---

## F4 — ATS score display + Accept/Download actions

**Spec refs:** spec §9, §6 (step 3 actions, step 4), §10

**Scope:** Frontend, review screen actions.

- Displays original vs tailored ATS match percentage (spec §9), labeled
  as a heuristic.
- Wires **Retry** (back to F2's retry call, replaces the preview in
  place) and **Generate**/accept (calls B9's accept endpoint, then
  surfaces download links) buttons.
- Download links for CV and, if present, cover letter, using the
  filenames the backend returns.

**Depends on:** F3, B8, B9.

**Verify:**
- Manual run: ATS percentages shown for both versions and the tailored
  number is visibly distinguished from the original.
- Clicking Retry replaces the preview with a new draft without a full
  page/session reset.
- Clicking Generate produces working downloads for CV (and cover letter,
  if uploaded) whose filenames match spec §10's convention, and the
  downloaded files open correctly with formatting intact.

---

## I1 — End-to-end acceptance pass

**Spec refs:** all of `specs/spec.md` and `architecture.md` — final
acceptance check against both as a whole.

**Scope:** Cross-cutting manual/scripted QA pass, no new feature code
expected (fixes only if gaps are found).

- Run the full flow against a real personal CV, a real cover letter, and
  a real job description end to end: upload → generate → review
  (preview + ATS score) → retry at least once → accept → download.
- Explicitly check each of the "should not" requirements from the
  original ask (spec §2/§7.2): no structural changes, no buzzwords, no
  robotic tone, simple language, formatting/colors/fonts/borders
  unchanged in untouched sections.
- Re-run the flow against the 2–3 differently-formatted CV fixtures used
  in B3's classifier tests — confirm no whole section is silently
  excluded from tailoring due to a classifier gap (architecture §4's
  known limitation); if one is found, file it as a follow-up against B3,
  don't patch ad hoc.
- Spot-check token usage/cost across a generate + 2 retries on the same
  session to confirm the caching/sparse-diff design is actually behaving
  as designed (retries visibly cheaper than the first call).
- Confirm no history/persistence is created beyond the session's on-disk
  files (spec §3 non-goals), and that a fresh session doesn't leak
  another session's files.

**Depends on:** F4 (and transitively everything else).

**Verify:** Each bullet above passed manually on a real, non-synthetic
document set; any failure is filed as a follow-up fix task against the
specific B/F task it belongs to, not patched ad hoc outside the task
breakdown.
