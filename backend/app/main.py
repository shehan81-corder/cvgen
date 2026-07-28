from fastapi import FastAPI

from app.config import ANTHROPIC_API_KEY  # noqa: F401  (import fails fast if unset)
from app.routers import generation, sessions

app = FastAPI(title="CVGen API")
app.include_router(sessions.router)
app.include_router(generation.router)


@app.get("/health")
def health():
    return {"status": "ok"}
