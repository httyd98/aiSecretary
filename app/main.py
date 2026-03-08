"""
Entry point FastAPI — SegretarioLLM
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import database as db
from app.webhook import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(
    title="SegretarioLLM",
    description="Assistente WhatsApp AI per professionisti",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
