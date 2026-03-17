"""FastAPI server for the hallucination firewall API."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import load_config
from .models import ValidationResult
from .pipeline.runner import ValidationPipeline

logger = logging.getLogger(__name__)

RATE_LIMIT = 60  # requests per window
RATE_WINDOW = 60  # seconds


class MetricsCollector:
    """In-memory metrics collector for observability."""

    def __init__(self) -> None:
        self.request_count = 0
        self.error_count = 0
        self.total_latency_ms = 0.0
        self.cache_hits = 0
        self.cache_misses = 0
        self.latency_histogram = {
            "<100ms": 0,
            "<500ms": 0,
            "<1000ms": 0,
            ">1000ms": 0,
        }

    def record_request(self, latency_ms: float, is_error: bool = False) -> None:
        """Record a request with its latency."""
        self.request_count += 1
        self.total_latency_ms += latency_ms

        if is_error:
            self.error_count += 1

        # Update histogram
        if latency_ms < 100:
            self.latency_histogram["<100ms"] += 1
        elif latency_ms < 500:
            self.latency_histogram["<500ms"] += 1
        elif latency_ms < 1000:
            self.latency_histogram["<1000ms"] += 1
        else:
            self.latency_histogram[">1000ms"] += 1

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1

    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self.cache_misses += 1

    def get_metrics(self) -> dict[str, Any]:
        """Return all metrics as a dictionary."""
        avg_latency = (
            self.total_latency_ms / self.request_count if self.request_count > 0 else 0
        )
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "avg_latency_ms": round(avg_latency, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": (
                round(self.cache_hits / (self.cache_hits + self.cache_misses), 3)
                if (self.cache_hits + self.cache_misses) > 0
                else 0
            ),
            "latency_histogram": self.latency_histogram,
        }


metrics = MetricsCollector()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP sliding-window rate limiter."""

    def __init__(self, app: Any, limit: int = RATE_LIMIT, window: int = RATE_WINDOW) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        # Prune old timestamps
        recent = [t for t in self._requests[client_ip] if now - t < self.window]
        if not recent:
            self._requests.pop(client_ip, None)
            recent = []
        else:
            self._requests[client_ip] = recent
        if len(recent) >= self.limit:
            return JSONResponse(
                {"detail": "Rate limit exceeded"}, status_code=429
            )
        self._requests[client_ip].append(now)
        return await call_next(request)

pipeline: ValidationPipeline | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage pipeline lifecycle."""
    global pipeline
    config = load_config()
    pipeline = ValidationPipeline(config)

    # Wrap cache.get to track hits/misses
    original_get = pipeline.cache.get

    def wrapped_get(key: str) -> Any:
        result = original_get(key)
        if result is not None:
            metrics.record_cache_hit()
        else:
            metrics.record_cache_miss()
        return result

    pipeline.cache.get = wrapped_get  # type: ignore[method-assign]

    yield
    try:
        await pipeline.close()
    except Exception:
        logger.exception("Error closing pipeline during shutdown")


app = FastAPI(
    title="AI Hallucination Firewall",
    description="Validates AI-generated code against real sources",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)


class ValidateRequest(BaseModel):
    """Request body for code validation."""

    code: str
    file_path: str = "<api>"
    language: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/validate", response_model=ValidationResult)
async def validate(request: ValidateRequest) -> ValidationResult:
    """Validate code for hallucinated APIs and patterns."""
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    start_time = time.time()
    is_error = False

    try:
        file_path = request.file_path
        if request.language:
            file_path = f"{file_path}.{request.language}"

        result = await pipeline.validate_code(request.code, file_path)
        return result

    except Exception:
        is_error = True
        raise

    finally:
        latency_ms = (time.time() - start_time) * 1000
        metrics.record_request(latency_ms, is_error)


@app.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """Return server metrics."""
    return metrics.get_metrics()
