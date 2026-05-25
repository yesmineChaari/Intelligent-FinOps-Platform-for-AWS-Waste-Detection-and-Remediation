"""FastAPI application for read-only dashboard data access."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import close_pool, open_pool
from app.routers import alerts, ec2, guardrails, overview, phase3, runs, s3


load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await open_pool()
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(
    title="PFA FinOps Dashboard API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

for route_module in (overview, ec2, s3, guardrails, phase3, alerts, runs):
    app.include_router(route_module.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
