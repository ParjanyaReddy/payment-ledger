"""Telemetry, Structured JSON Logging, and Prometheus Metrics Engine.

This module provides enterprise-grade observability:
1. Context-aware Request ID propagation (X-Request-ID).
2. Structured JSON logging format for log aggregation (Datadog, Loki, CloudWatch).
3. Prometheus metrics instrumentation (/metrics) tracking request rate, duration, and financial events.
"""

import contextvars
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Context variable for storing the active request ID across async coroutines
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def get_current_request_id() -> str:
    """Return the active request ID for the current execution context."""
    return request_id_ctx.get()


# ---------------------------------------------------------------------------
# Structured JSON Log Formatter
# ---------------------------------------------------------------------------
class JSONLogFormatter(logging.Formatter):
    """Custom logging formatter outputting clean, machine-parsable JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_current_request_id() or None,
            "module": record.module,
            "line": record.lineno,
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure standard logging to output structured JSON to stdout."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Replace existing handlers
    root_logger.handlers = [handler]

    # Silence excessive engine pool noise in standard logs
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.access").propagate = False


# ---------------------------------------------------------------------------
# Prometheus Metrics Registry
# ---------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests served by the API",
    ["method", "endpoint", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency histogram in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

TRANSFERS_PROCESSED_TOTAL = Counter(
    "transfers_processed_total",
    "Total number of double-entry transfers executed",
    ["status"],
)

CARD_AUTHORIZATIONS_TOTAL = Counter(
    "card_authorizations_total",
    "Total card authorizations processed",
    ["status"],
)

RECONCILIATION_RUNS_TOTAL = Counter(
    "reconciliation_runs_total",
    "Total automated financial reconciliation runs executed",
    ["status"],
)


# ---------------------------------------------------------------------------
# Telemetry & Request ID Middleware
# ---------------------------------------------------------------------------
class TelemetryMiddleware(BaseHTTPMiddleware):
    """Starlette middleware for Request ID tracing and Prometheus metric collection."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 1. Extract or generate UUID v4 Request ID
        req_id = request.headers.get("X-Request-ID")
        if not req_id:
            req_id = str(uuid.uuid4())

        # Set context variable for downstream logs
        token = request_id_ctx.set(req_id)
        start_time = time.perf_counter()

        endpoint_path = request.url.path
        method = request.method
        logger = logging.getLogger("app.access")

        try:
            response = await call_next(request)
            duration_s = time.perf_counter() - start_time
            duration_ms = duration_s * 1000.0

            # Record Prometheus metrics (skip /metrics itself to prevent metric scrape recursion)
            if endpoint_path != "/metrics":
                status_str = str(response.status_code)
                HTTP_REQUESTS_TOTAL.labels(
                    method=method, endpoint=endpoint_path, status_code=status_str
                ).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint_path).observe(
                    duration_s
                )

                # Log structured access event
                logger.info(
                    f"{method} {endpoint_path} {response.status_code} ({duration_ms:.2f}ms)",
                    extra={
                        "method": method,
                        "path": endpoint_path,
                        "status_code": response.status_code,
                        "duration_ms": round(duration_ms, 2),
                    },
                )

            # Inject Request ID into response header
            response.headers["X-Request-ID"] = req_id
            return response

        except Exception as exc:
            duration_s = time.perf_counter() - start_time
            if endpoint_path != "/metrics":
                HTTP_REQUESTS_TOTAL.labels(
                    method=method, endpoint=endpoint_path, status_code="500"
                ).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint_path).observe(
                    duration_s
                )
                logger.exception(
                    f"Unhandled exception during {method} {endpoint_path}: {exc}",
                    extra={"method": method, "path": endpoint_path, "status_code": 500},
                )
            raise exc

        finally:
            request_id_ctx.reset(token)


async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics scrape endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
