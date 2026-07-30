# CVGen — Architecture (Option B: Two-Stage Pipeline)

Companion to [`specs/spec.md`](specs/spec.md), which defines *what* the app
must do. This document defines *how* it's built, specifically the design
chosen to minimize LLM token usage while strengthening the spec's
"don't change structure/dates/titles/formatting" requirement.

Selected design: **deterministic pre-filter (Stage 0) + sparse-diff LLM
call (Stage 1)**, in place of a single call that sends and re-receives
every block. Rationale is in the conversation that led here — summarized
in §7 below.

## 1. Design goals

- Minimize tokens sent to and received from the LLM, on every generate
  *and* every retry (not just the first call).
- Make "the model cannot alter dates/titles/headers/contact info" a
  structural guarantee, not a prompt-following hope.
- Keep the docx formatting-preservation guarantee from spec §7.1 (write
  text back into existing runs, never rebuild structure) unchanged.

## 2. Component overview

```
                         ┌─────────────────────────────┐
                         │  Frontend (React)            │
                         └──────────────┬────────────────┘
                                        │ REST
                         ┌──────────────▼────────────────┐
                         │  API layer (FastAPI)           │
                         └──────────────┬────────────────┘
                                        │
        ┌───────────────────┬──────────┼───────────┬────────────────┐
        ▼                   ▼          ▼            ▼                ▼
 ┌─────────────┐   ┌────────────────┐ ┌──────────┐ ┌─────────────┐ ┌──────────────┐
 │ Block        │   │ Block           │ │ LLM      │ │ Docx writer │ │ ATS scoring  │
 │ extraction   │──▶│ classifier      │ │ rewrite  │ │ + preview   │ │ service      │
 │ (docx→blocks)│   │ (stage 0, rules)│ │ (stage 1)│ │ builder     │ │ (independent)│
 └─────────────┘   └────────────────┘ └────┬─────┘ └─────────────┘ └──────────────┘
                                            │
                                    ┌───────▼────────┐
                                    │ Claude API      │
                                    │ (prompt-cached  │
                                    │  system+context)│
                                    └─────────────────┘

 Session storage: ./data/session-<uuid>/  — raw files, extracted+classified
 block lists (JSON), generated drafts, final output docx files.
```

Everything downstream of "block extraction" is new or changed relative to
the original single-call design; upload/session/ATS/docx-writer
responsibilities are the same components described in `tasks.md`'s B-series,
just re-sequenced.

## 3. Block model

Extraction (unchanged from spec §7.1) walks the docx and emits one entry
per run/paragraph:

```json
{
  "id": "p12-r0",
  "text": "Led migration of the billing service to a new provider.",
  "location": { "paragraph": 12, "run": 0 },
  "style": { "font": "Calibri", "size": 11, "color": "#000000", "bold": false, "italic": false, "underline": false },
  "section": "experience"        // added by classifier, see §4
}
```

`section` and the classifier's `editable` flag (§4) are computed once,
at upload time, and stored alongside the raw block list in the session
directory — not recomputed on every generate/retry.

## 4. Stage 0 — Block classifier (deterministic, no LLM)

Runs once per uploaded document (CV, and cover letter if present),
immediately after extraction, before the document is available for
generation.

**Inputs:** the raw block list + paragraph style names from the docx
(e.g. `Heading1`, `Heading2`, `Normal`, `ListParagraph`) + simple regexes.

**Classification rules (applied in order, first match wins):**

1. **Section boundary detection:** paragraphs using heading styles (or
   all-caps short lines, a common CV convention when headings aren't
   styled) mark the start of a new section; the section name is matched
   against a small known-alias list (`experience`/`work history`,
   `summary`/`profile`, `skills`, `education`, `projects`, `certifications`,
   `contact`, etc.) via case-insensitive substring match.
2. **Fixed patterns, regardless of section:**
   - Matches an email, phone, URL, or postal-address-like pattern →
     `fixed` (contact info).
   - Matches a date/date-range pattern (`\b(19|20)\d{2}\b`, month names,
     "Present") in a short line → `fixed` (dates are never rephrased).
   - Is itself a heading-styled paragraph → `fixed` (section titles).
   - Is the first line under `education`/`experience` matching a
     "Title, Company" or "Degree, Institution" shape (short line,
     title-case, no sentence punctuation) → `fixed` (job titles, company
     names, degree names, institution names).
3. **Section-based default (`document_type="cv"`):**
   - Inside `experience`, `summary`, `skills`, `projects` → `editable`.
   - Inside `education`, `certifications`, `contact`, or unrecognized
     sections → `fixed` (conservative default: unfamiliar territory is
     left alone rather than risking an edit to something factual).

**Cover letters get a different default (`document_type="cover_letter"`):**
found via I1's first real-document run — a cover letter has no CV-style
section headings at all (no "Experience", no "Skills"), so the CV's
section-based default left the *entire letter* classified `fixed` with
zero editable blocks. Cover letters instead: still protect contact info
and dates (rule 2), additionally protect salutation lines ("Dear ...,")
and sign-offs ("Yours sincerely," + the name line that follows), and
default everything else to `editable` if it's long enough to be genuine
body prose (≥6 words) rather than a short letterhead/address/subject-line
fragment. No section-heading tracking is involved for cover letters at
all.

**Output:** every block gets `section` + `editable: true|false`. This is
persisted with the block list — it's what Stage 1 uses to decide what to
even show the model, and what the docx writer uses to guarantee `fixed`
blocks are never touched.

**Known limitation (tracked, not solved in v1):** a CV using unconventional
styling (no heading styles, unusual section names) can misclassify an
`editable` block as `fixed`, causing that section to silently never be
tailored — no error, just missed opportunity. Mitigated by:
- Conservative defaults (§4.3) bias toward `fixed`, so failures are
  "missed a bullet" rather than "rewrote a job title."
- The diff-preview UI (§6) shows section labels per block, so a user
  can visually notice a whole section rendered with zero highlights and
  report it.
- I1 (acceptance pass) explicitly tests against 2–3 real, differently
  formatted CVs, not just one synthetic fixture, to catch classifier gaps
  before they reach real use. This is how the cover-letter gap above was
  actually found and fixed, and how the next limitation was found (not
  yet fixed):
- Left as an explicit open item for a future "mark this block as
  editable" manual override (see spec §13's existing open questions).

**Known limitation #2 (found by I1, not fixed — filed as a follow-up):**
a document whose runs are heavily fragmented mid-sentence (common after
copy-pasting or heavy in-place editing in Word — e.g. "...I currently
lead " / "an " / "engineering as Senior Engineering Manager...", where
the middle run happens to land on a `fixed` pattern) can leave a genuine
sentence half-`editable`, half-`fixed`. The LLM (correctly, per its
"preserve structure" instruction) tends to decline editing a fragment
that would risk breaking grammatical continuity with its frozen
neighbor — so the block goes untouched, not incorrectly, but
conservatively to the point of missing real tailoring opportunity. This
was observed on a real cover letter during I1: 7 blocks were correctly
classified `editable`, but 2 of the least fragmented ones were the only
plausible edit targets — the model touched none of them across 5 sample
calls. Fixing this properly means merging adjacent same-style runs into
one block *before* extraction/classification (see `docx_blocks.py`), so
a full sentence is one editable unit instead of an arbitrary Word-run
split — a `docx_blocks.py`-level change, not a classifier one. Tracked
as a follow-up task, not patched ad hoc during I1.

## 5. Stage 1 — LLM rewrite (sparse diff, combined CV + cover letter)

**One LLM call per generate/retry**, covering the CV's `editable` blocks
and (if a cover letter template was uploaded) its `editable` blocks too,
against the same job description — one system prompt instead of two,
halving fixed overhead per call.

**Request contents:**
- System prompt: the rules from spec §7.2 (no fabrication, preserve
  structure/tone/vocabulary, no buzzwords, plain language, factual fields
  never touched) plus the sparse-output contract below.
- User content: job description text + the `editable` block list only
  (id + text, no style metadata — the model never needs it) for the CV,
  and the same for the cover letter if present, clearly separated.

**Sparse output contract:** the model returns *only* the blocks it
changes — `[{ "id": "...", "text": "..." }, ...]`. Anything not present
in the response is treated as unchanged. This is the core token saving
over the original design: no requirement to echo every unchanged block's
ID/status back.

**Validation (replaces spec §11's "block count/ID mismatch" check):**
- Every returned `id` must be a member of the `editable` set that was
  sent for that document. Any id outside that set (e.g. the model tries
  to "helpfully" edit a `fixed` block, or hallucinates an id) is a hard
  validation failure — reject the whole response, surface a retryable
  error, never partially apply it.
- No minimum/maximum count check is meaningful anymore (an empty response
  — "nothing worth changing" — is valid), but a response that changes
  *zero* blocks across both documents is flagged to the user as a
  low-confidence result worth a manual retry, not silently treated as
  success.

**Prompt caching:** the system prompt + editable-block context is sent as
a cached prefix. A **retry** re-issues the same prefix (cache hit within
TTL) with only a fresh sampling request appended — retries cost roughly
the "new draft" marginal tokens, not the full input again. After cache
TTL expiry (idle session), the next call simply pays full price and
re-establishes the cache — no special handling needed, this degrades
gracefully.

## 6. Docx writer & diff-preview builder

Unchanged in mechanism from spec §7.1/§8 (write text into existing runs,
never touch structure) but now driven by the sparse diff:

- For each document, start from "all blocks unchanged."
- Apply Stage 1's sparse changes by block id — only those runs' text is
  replaced.
- `fixed` blocks are structurally never candidates — the writer doesn't
  need special-case logic to protect them; they were simply never in the
  set the LLM could have returned an id for.
- Preview JSON per block now also carries `section` and `editable` (in
  addition to the existing changed/unchanged flag from spec §8), so the
  frontend can render `fixed` blocks distinctly (e.g. muted, "not
  eligible for editing") from `editable`-but-unchanged blocks (e.g.
  normal, "the model chose not to change this") — useful for spotting
  classifier gaps per §4's mitigation.

## 7. Why this over a single full-context call

| | Single call (all blocks, full round-trip) | Two-stage (this design) |
|---|---|---|
| Input tokens/call | Every block, every retry | Only `editable` blocks; `fixed` ones never sent |
| Output tokens/call | Every block echoed (with status) | Only changed blocks |
| Retry cost | Same as first call (cache-dependent) | Same input shrinkage applies every time |
| Structural safety for dates/titles/headers | Prompt-instruction only | Structural — model never sees them |
| New engineering surface | None | Stage 0 classifier + its edge cases |

The classifier is the real cost of this design — it's new code with its
own failure mode (§4's limitation) — but it pays for itself on both token
cost and correctness, so it's worth the extra build/test effort.

## 8. ATS scoring (unaffected)

Spec §9's ATS scoring runs on full CV text (not just `editable` blocks —
a keyword could legitimately live in a `fixed`-classified line, e.g. a
skill embedded in a job title) and stays a standalone deterministic
service with no LLM involvement, as originally specified.

## 9. Session storage additions

Per session directory, in addition to raw uploaded files and final
outputs:
- `cv_blocks.json` / `cover_letter_blocks.json` — extracted + classified
  block lists, computed once at upload, reused by every generate/retry
  call in that session (classification never needs to re-run).
- `draft_<n>.json` — each generate/retry's sparse diff response, kept for
  the duration of the session so `accept` can apply the exact draft the
  user reviewed, not risk re-invoking the LLM at accept time.
