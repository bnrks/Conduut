from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.logging_config import bind_log_context, clear_log_context, configure_logging
from src.registry import initialize_registry
from src.routes import artifacts as artifacts_router
from src.routes import chat, conversations
from src.routes import connections as connections_router
from src.routes import credentials as credentials_router
from src.routes import workflows as workflows_router

configure_logging()

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("conduut_agent_starting", environment=settings.environment)
    await initialize_registry(settings.n8n_url)
    yield
    log.info("conduut_agent_stopping")


app = FastAPI(title="Conduut Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def diagnostic_request_logging(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    clear_log_context()
    bind_log_context(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    started_at = perf_counter()
    log.info("http_request_started")
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        log.error(
            "http_request_error",
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        clear_log_context()
        raise

    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "http_request_finished",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    clear_log_context()
    return response


app.include_router(chat.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(artifacts_router.router, prefix="/api")
app.include_router(credentials_router.router, prefix="/api")
app.include_router(connections_router.router, prefix="/api")
app.include_router(workflows_router.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent"}
