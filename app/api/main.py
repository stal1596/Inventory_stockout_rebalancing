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

from fastapi import FastAPI, HTTPException
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

# The SPA catch-all below must stay last, or a DEFINED route would be shadowed by
# index.html. Ordering alone does not protect UNDEFINED /api paths -- those still
# fall through to the catch-all, which is why `spa` refuses them explicitly.
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
#
# Guarding on the ASSETS directory rather than on `dist` alone: StaticFiles raises
# at construction time when its directory is missing, so an interrupted `vite
# build` that left an index.html behind would take the API down with the UI.
if (WEB_DIST / "index.html").is_file():
    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        """Client-side routing: unknown paths return index.html, not a 404.

        Two refusals, both of which used to be missing.

        **An unmatched /api path is a 404, not the shell.** Being registered last
        only protects the routes that exist; `/api/typo` matched nothing above and
        arrived here, and returning index.html with a 200 meant the frontend's
        `get()` sailed past its error handler and called `.json()` on HTML. A
        missing endpoint therefore surfaced as an opaque parse error rather than
        as a 404 -- which is what "could not reach the API" looked like.

        **A path may not escape the build directory.** `StaticFiles` (mounted at
        /assets) contains its own paths; this hand-rolled handler did not, so a
        request carrying `..` segments served arbitrary files from the repo.
        """
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"No such endpoint: /{full_path}")

        root = WEB_DIST.resolve()
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
