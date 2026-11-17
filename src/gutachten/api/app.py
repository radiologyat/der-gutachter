# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application. Serves the API and (if built) the web frontend.

Run:  uv run python -m gutachten.api.app
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..analysis.steps import manual_change_step, touch
from ..cases import CaseNotFound
from .routes import router

WEB_DIST = config.WEB_DIST


def create_app() -> FastAPI:
    config.ensure_dirs()
    app = FastAPI(title="Der Gutachter", docs_url="/api/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://{config.API_HOST}:{config.API_PORT}",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Reject requests whose Host header isn't local. Blocks DNS-rebinding
    # attacks in which a website resolves its own domain to 127.0.0.1 and reads
    # patient data through the user's browser.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=sorted({"127.0.0.1", "localhost", config.API_HOST}),
    )

    @app.exception_handler(CaseNotFound)
    async def _case_not_found(_req: Request, exc: CaseNotFound) -> JSONResponse:
        return JSONResponse({"detail": f"case not found: {exc.args[0]}"}, status_code=404)

    @app.middleware("http")
    async def _mark_manual_changes(request: Request, call_next):
        """A successful manual correction makes everything downstream stale."""
        response = await call_next(request)
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400:
            hit = manual_change_step(request.url.path)
            if hit:
                touch(*hit)
        return response

    app.include_router(router)
    if WEB_DIST.exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "gutachten.api.app:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
