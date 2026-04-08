from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.routes import chat, conversations, favorites as favorites_router, settings as settings_router

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("conduut_agent_starting", environment=settings.environment)
    yield
    log.info("conduut_agent_stopping")


app = FastAPI(title="Conduut Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(favorites_router.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent"}
