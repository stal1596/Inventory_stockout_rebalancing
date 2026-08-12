"""FastAPI application for the supply-chain control tower.

    uv run uvicorn app.api.main:app --reload

The first request blocks for ~32 seconds while the extract loads and the model
fits; every request after that is served from memory. ``--reload`` re-pays that
cost on each code change, which is why the state lives in a module-level
singleton rather than in application scope.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import (
    backtest,
    catalog,
    evidence,
    exports,
    overview,
    policy,
    prescribe,
    quality,
    risk,
    simulate,
)
from app.api.state import get_state

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("controltower")

WEB_DIST = Path(__file__).resolve().parents[2] / "app" / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the cache at startup so the first user request is fast rather than
    # paying the 32-second fit.
    log.info("warming application state...")
    state = get_state()
    log.info(
        "ready: %s open positions, C-index %.3f, %.1fs",
        len(state.scored), state.c_index, state.load_seconds,
    )
    yield


app = FastAPI(
    title="Supply Chain Control Tower",
    description="Descriptive -> predictive -> simulation -> prescriptive, over a "
                "survival model with exact driver attribution.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Order matters only against the SPA catch-all below, which must stay last or an
# unmatched /api path would be served index.html instead of a 404.
for router in (overview.router, risk.router, simulate.router, prescribe.router,
               catalog.router, evidence.router, quality.router, policy.router,
               backtest.router, exports.router):
    app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    state = get_state()
    return {
        "status": "ok",
        "as_of": state.as_of.strftime("%Y-%m-%d"),
        "positions": len(state.scored),
        "c_index": round(state.c_index, 3),
        "load_seconds": round(state.load_seconds, 1),
    }


# Serve the built SPA when it exists, so one process runs the whole product.
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        """Client-side routing: unknown paths return index.html, not a 404."""
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
