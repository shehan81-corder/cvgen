# CVGen — Job-Tailored CV & Cover Letter Generator

## 1. Overview

A small, personal, local web app that takes an existing CV (.docx) and a job
description, and produces a tailored version of the CV — better aligned with
the job description and ATS-friendly — while preserving the original
document's structure, tone, language, and visual formatting. It also
generates a matching cover letter from an existing cover letter template,
following the same rules. The user reviews a side-by-side diff, can retry
the generation, and on approval the result is saved as a .docx file.

Single user, runs locally, no accounts, no history/persistence beyond the
current session's output files on disk.

## 2. Goals

- Rewrite CV content so it aligns better with a given job description and
  is more likely to pass ATS keyword screening.
- Preserve the original CV's:
  - Section structure and ordering
  - Sentence/bullet structure and logical flow
  - Language pattern and tone (the user's own voice)
  - Visual formatting: fonts, font sizes, colors, borders, layout
- Never introduce AI buzzwords, jargon, or robotic-sounding phrasing.
- Keep language simple and close to the original wording — this is
  targeted rewriting (word/phrase-level substitution and emphasis
  shifting), not a rewrite from scratch.
- Show the user exactly what changed before anything is finalized.
- Let the user retry generation if unhappy with the result.
- Generate a cover letter using the same input job description and the
  user's existing cover letter as a style/structure template.

## 3. Non-goals

- No multi-user support, authentication, or accounts.
- No persistent history of past applications/generations.
- No PDF CV formatting reproduction — PDF is not accepted as a CV/cover
  letter source (see §5.1).
- No support for output formats other than .docx.
- No hosted/cloud deployment — this runs on the user's machine.
- No general-purpose resume builder (no template gallery, no building a CV
  from nothing).

## 4. Tech stack

- **Backend:** Python, FastAPI
- **Frontend:** React (Vite), served locally
- **CV/cover letter editing:** `python-docx` — edits text runs in place
  inside the existing .docx structure so fonts, colors, sizes, and borders
  are inherently preserved (we mutate existing runs rather than rebuilding
  the document).
- **LLM:** Anthropic Claude API (see §7 for prompt/rules design)
- **API key:** read from a local `.env` file (`ANTHROPIC_API_KEY`) at
  backend startup. Never sent to the frontend, never logged.
- **Storage:** local filesystem only. No database. Uploaded files and
  generated outputs live in a working directory for the duration of the
  session (e.g. `./data/session-<uuid>/`), which can be cleared at any
  time with no loss of durable data.

## 5. Inputs

### 5.1 File requirements

| Input | Accepted format | Notes |
|---|---|---|
| CV | `.docx` only | Formatting fidelity requires editing the real docx styles — PDF is rejected with a clear error message asking for the Word version. |
| Job description | Pasted text, or `.docx`/`.pdf` upload | It's consumed as plain text only, so format fidelity doesn't matter here — PDF text extraction is fine. |
| Cover letter template | `.docx` only | Same reasoning as CV. Optional — if omitted, cover letter generation is skipped for that session. |

### 5.2 Upload validation

- Reject non-.docx CV/cover letter uploads at upload time with a specific
  error ("Please upload the Word (.docx) version of your CV — PDF can't
  preserve exact formatting").
- Cap file size (e.g. 10 MB) to avoid pathological uploads.
- Parse-on-upload: immediately attempt to open with `python-docx` and fail
  fast with a clear error if the file is corrupt/unsupported (e.g.
  password-protected).

## 6. User flow

1. **Upload screen**
   - Upload CV (.docx, required)
   - Upload cover letter (.docx, optional)
   - Paste or upload job description (required)
2. **Generate**
   - User clicks "Generate". Backend runs the CV tailoring pass (§7) and,
     if a cover letter template was provided, the cover letter pass.
   - Loading state while the LLM call(s) run.
3. **Review screen**
   - Side-by-side rendered preview: original CV (left) vs. tailored CV
     (right), with changed text highlighted (§8).
   - Same side-by-side view for the cover letter, if generated.
   - A computed ATS match score is shown for original vs. tailored version
     (§9).
   - Actions:
     - **Retry** — re-runs generation with the same inputs (LLM sampling
       naturally varies the result), replaces the preview.
     - **Generate** (i.e. accept) — finalizes the current draft, writes it
       to a .docx file preserving the original formatting, and makes it
       available to download.
4. **Done**
   - Tailored CV (and cover letter, if applicable) available as
     downloadable .docx files.

## 7. Rewriting engine (LLM-based)

### 7.1 Approach

Full technical design lives in [`architecture.md`](../architecture.md).
Summary:

Extract the text content run-by-run (or paragraph-by-paragraph) from the
.docx using `python-docx`, keeping a stable mapping from each text block to
its location in the document (paragraph index, run index). Before any LLM
call, each block is deterministically classified as `editable` (content
likely to benefit from tailoring — experience/summary/skills/projects
bullets) or `fixed` (dates, headers, job titles, company/institution names,
contact info — never touched, by construction, not just by instruction).

Only `editable` blocks, plus the job description text, are sent to Claude.
The model returns a *sparse* list of the blocks it actually changes —
unchanged blocks are simply omitted from the response, not echoed back.
We then write the replacement text back into the *existing* runs at their
original locations, so the run's formatting (font, size, color,
bold/italic, etc.) is untouched — only the text content changes.

This block-level, in-place substitution approach — combined with `fixed`
blocks being structurally excluded from what the model ever sees — is what
mechanically guarantees the "don't change structure or formatting"
requirements, and minimizes tokens sent/received on every generate and
retry.

### 7.2 Prompt rules (enforced via system prompt + validated post-hoc)

The model must be instructed to:

- Only adjust wording to better reflect terms/skills/priorities from the
  job description where truthfully applicable to the user's actual
  experience — never fabricate skills, experience, or claims not already
  present in some form in the original CV.
- Preserve the original sentence structure and logical flow — this is
  light editing (swap a word/phrase, reorder emphasis within a bullet),
  not a rewrite.
- Preserve the user's existing tone and vocabulary level — reuse the
  user's own words wherever possible.
- Never introduce AI/marketing buzzwords ("synergize", "leverage",
  "spearheaded", "results-driven", "dynamic", "cutting-edge", etc.) or
  jargon not already present in the source CV or job description.
- Use plain, simple, human language — avoid anything that reads as
  generated or overly polished.
- Do not change section headers, dates, job titles, company names, or any
  factual content. (Enforced doubly: these are classified `fixed` and
  structurally never sent to the model — see `architecture.md` §4.)
- Return only the blocks actually changed (id + new text). Anything not
  returned is treated as unchanged — sparse by design, to minimize output
  tokens. See `architecture.md` §5 for the exact contract and validation
  rules.

### 7.3 Cover letter

Same block-level substitution approach applied to the uploaded cover
letter template: reuse its structure/paragraphs, adjust content to
reference the specific job/company/role from the job description, subject
to the same buzzword/tone/simplicity rules as §7.2. The CV and cover
letter are sent to the model in a single combined call (shared system
prompt + job description) rather than two separate calls, per
`architecture.md` §5.

### 7.4 Retry

Retry re-issues the same request (same `editable` blocks + same job
description). No caching of the *previous output* is used as context —
each retry is an independent generation, relying on normal LLM sampling
variance to produce a different draft. The request's static context
(system prompt + blocks + job description) is prompt-cached so a retry's
token/latency cost is dominated by the new draft alone, not a full resend
— see `architecture.md` §5.

## 8. Side-by-side diff preview

- Rendered document preview (not raw text): each side renders the
  document's paragraphs with their real formatting (font, size, color)
  pulled from the docx, so the preview visually resembles the actual
  Word document.
- Changed blocks are highlighted (e.g. background highlight) on the right
  (tailored) side; the corresponding original block is shown unhighlighted
  on the left for comparison.
- Unchanged-but-editable blocks render plainly on both sides with no
  highlight. Blocks classified `fixed` (see `architecture.md` §4 — dates,
  headers, titles, contact info) render distinctly muted/labeled as "not
  eligible for editing," so a user can visually spot a whole section that
  was excluded from tailoring rather than one the model simply left alone.
- Implementation note: backend converts each paragraph/run into a
  lightweight JSON structure (text + font family + size + color + bold/
  italic/underline + editable/fixed classification) for the frontend to
  render as styled HTML — no need for a full docx-to-HTML converter or PDF
  rendering.

## 9. ATS match score

- Computed, not model-generated (deterministic and comparable across
  original/tailored versions).
- Approach: extract candidate keywords/phrases from the job description
  (e.g. noun phrases, known skill/tool terms, repeated significant terms),
  then compute the fraction of those keywords present in the CV text
  (case-insensitive, simple stemming/lemmatization for matching plural/verb
  forms).
- Display as a percentage for both the original CV and the tailored CV
  side by side (e.g. "Original: 42% → Tailored: 71%") so the user can see
  the improvement.
- This is a rough heuristic indicator, not a claim of real ATS system
  compatibility — labeled as such in the UI.

## 10. Output

- On clicking **Generate** (accept), the backend writes the final tailored
  content into a copy of the original .docx (formatting preserved as
  described in §7.1) and saves it to disk.
- Same for the cover letter, into a copy of the original cover letter
  .docx, if one was provided.
- Filenames: `<original-cv-name>-tailored-<job-company-or-role-slug>.docx`
  and `<original-cover-letter-name>-tailored-<job-company-or-role-slug>.docx`.
- Files are made available via a download link/button in the UI.

## 11. Error handling

- Non-.docx CV/cover letter upload → reject with explanation (§5.2).
- Corrupt/unparseable .docx → reject with explanation.
- Missing job description → block Generate button, inline validation
  message.
- LLM call failure (network/API error) → show retry option, don't lose
  uploaded inputs.
- LLM returns a block id outside the `editable` set it was sent → treat as
  a failed generation, surface an error, allow retry (never silently
  apply an out-of-scope edit). See `architecture.md` §5.

## 12. Architecture summary

Full component design, data flow, and the token-minimization strategy are
in [`architecture.md`](../architecture.md). High level:

```
frontend (React, Vite)
   |
   |  REST calls: upload CV/cover letter/JD, trigger generate, trigger retry,
   |  fetch preview JSON, download final .docx
   v
backend (FastAPI)
   |-- upload handlers: validate + parse .docx via python-docx,
   |                    extract paragraph/run text + style metadata
   |-- block classifier: deterministic editable/fixed tagging per block
   |                      (dates, headers, titles, contact info -> fixed)
   |-- job description handler: accept pasted text or extract text from
   |                             uploaded .docx/.pdf
   |-- generation service: single combined call (CV + cover letter) over
   |                        `editable` blocks only, sparse-diff response,
   |                        prompt-cached for cheap retries
   |-- ats scoring service: keyword extraction + match % calculation
   |-- docx writer: write approved block text back into original docx's
   |                 runs (CV and/or cover letter), save to disk
   `-- session/file storage: local working directory per session, no DB
      (also holds classified block lists + per-draft sparse diffs)
```

## 13. Open questions / future considerations

(Not required for v1, flagged for later if desired)

- Should the user be able to edit individual blocks manually in the review
  screen before accepting, rather than only retry-the-whole-thing?
- The block classifier (`architecture.md` §4) can miscategorize an
  `editable` block as `fixed`, silently excluding it from tailoring.
  Should there be a manual override in the review screen to mark a
  `fixed` block as editable (or vice versa) and regenerate?
- If the CV uses tables (common for skills sections), confirm
  `python-docx` table cell run editing is handled the same way as
  paragraph runs — needs a v1 implementation check.
