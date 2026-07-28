# CVGen

Job-tailored CV & cover letter generator. See [`specs/spec.md`](specs/spec.md)
for the product spec, [`architecture.md`](architecture.md) for the technical
design, and [`tasks.md`](tasks.md) for the implementation task breakdown.

## Running locally

Two servers: a FastAPI backend and a Vite/React frontend, run separately.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in ANTHROPIC_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/health` → `{"status":"ok"}`

The backend refuses to start if `ANTHROPIC_API_KEY` isn't set in `backend/.env`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens on `http://localhost:5173`. Requests to `/api/*` are proxied to the
backend on port 8000 (see `frontend/vite.config.ts`), so both servers must be
running for the app to work end to end.

## Session data

Uploaded files and generated drafts are stored per-session under `./data/`
at the repo root (gitignored). No database — see `architecture.md` §9.
