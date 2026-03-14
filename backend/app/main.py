"""
AI Trader v2 – FastAPI Application Factory
==========================================
"""

import structlog
from fastapi import FastAPI

from app.api.v1.router import v1_router
from app.core.config import get_settings
from app.middleware.cors import add_cors_middleware
from app.middleware.logging import LoggingMiddleware


def configure_logging(settings) -> None:
    """Configure structlog for structured JSON logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="AI Trader API",
        version=settings.APP_VERSION,
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
        openapi_url="/api/openapi.json" if settings.DEBUG else None,
    )

    # Middleware (order matters – last added = first executed)
    add_cors_middleware(app)
    app.add_middleware(LoggingMiddleware)

    # Routes
    app.include_router(v1_router)

    @app.on_event("startup")
    async def on_startup():
        logger = structlog.get_logger("app")
        logger.info(
            "startup",
            version=settings.APP_VERSION,
            environment=settings.APP_ENV,
            debug=settings.DEBUG,
        )

    return app


app = create_app()
