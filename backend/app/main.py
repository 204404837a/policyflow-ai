"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, auth, cases, files, policies, review, upload, websocket
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.security import UploadValidationError


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="PolicyFlow AI", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (auth, upload, cases, review, files, policies, websocket):
        app.include_router(module.router)
    app.include_router(admin.router)
    app.include_router(admin.eval_router)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(UploadValidationError)
    async def _upload_error(_: Request, exc: UploadValidationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()
