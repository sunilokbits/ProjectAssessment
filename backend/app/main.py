from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, assessments, portfolio
from .config import ROOT, get_settings
from .db import SessionLocal, init_engine
from .engine import llm
from .engine.registry import sync_filesystem

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_engine()
    if s.sync_packs_on_startup:
        with SessionLocal() as db:
            rep = sync_filesystem(db, s.domain_packs_dir)
        log.info("domain packs: %d imported, %d unchanged, %d invalid",
                 len(rep["imported"]), len(rep["unchanged"]), len(rep["errors"]))
        for path, errs in rep["errors"].items():
            for e in errs:
                log.error("invalid pack %s -> %s: %s", path, e["location"], e["message"])
    yield


app = FastAPI(title="Project Assessment Tool – Domain Assessment Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(admin.router)
app.include_router(assessments.router)
app.include_router(portfolio.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_available": llm.available(), "ai_model": get_settings().ai_model}


# Serve the built React UI from the same container (single-image deployment).
STATIC_DIR = Path(os.getenv("PAT_STATIC_DIR", str(ROOT / "frontend" / "dist")))
if (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        f = (STATIC_DIR / path).resolve()
        if path and f.is_file() and STATIC_DIR.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")  # client-side routes
