"""FastAPI application entry point."""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add backend directory to path for agents import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.db.base import init_db
from app.api.endpoints import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    logger.info("Domain Expert API started")
    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="Domain Expert Multi-Agent System",
    description="AI-powered system for single-cell 3D genomics research",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "Domain Expert Multi-Agent System API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}
