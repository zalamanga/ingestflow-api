import asyncio
import hashlib
import hmac
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Query, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from . import models, store
from .config import Settings
from .db import connect
from .errors import APIError
from .validation import IDEMPOTENCY_KEY, MAX_BYTES

bearer = HTTPBearer(auto_error=False, scheme_name="TenantBearer", description="Private synthetic tenant key; supplied via Authorization: Bearer. Never put it in a query string.")


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="IngestFlow API", version="1.0.0",
        description="Durable, tenant-isolated CSV imports with PostgreSQL-backed leases and atomic record writes. Only synthetic inventory data is supported.",
        docs_url="/docs", redoc_url=None,
        responses={code: {"model": models.Error} for code in (400, 401, 404, 409, 413, 415, 422, 503)},
    )

    @app.exception_handler(APIError)
    async def domain_error(_request: Request, exc: APIError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError):
        return JSONResponse({"error": {"code": "invalid_request", "message": "Check path, header, and pagination parameter formats"}}, status_code=422)

    @app.exception_handler(psycopg.Error)
    async def database_error(_request: Request, _exc: psycopg.Error):
        return JSONResponse({"error": {"code": "database_unavailable", "message": "Database request could not finish; retry with the same idempotency key and CSV bytes"}}, status_code=503, headers={"Retry-After": "1"})

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def tenant(credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer" or len(credentials.credentials) != 64:
            raise APIError(401, "unauthorized", "A valid tenant bearer key is required")
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        alpha = hmac.compare_digest(digest, settings.alpha_digest)
        beta = hmac.compare_digest(digest, settings.beta_digest)
        if alpha:
            return "alpha"
        if beta:
            return "beta"
        raise APIError(401, "unauthorized", "A valid tenant bearer key is required")

    Tenant = Annotated[str, Depends(tenant)]

    @app.get("/health", tags=["Operations"])
    def health():
        with connect(settings) as conn:
            row = conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone()
            if not row:
                raise APIError(503, "migration_not_ready", "Database migration is not ready")
        return {"status": "ok"}

    @app.post("/v1/imports", response_model=models.Job, status_code=202, tags=["Imports"],
              openapi_extra={"requestBody": {"required": True, "content": {"text/csv": {"schema": {"type": "string"}, "example": "sku,name,quantity\nPEN-001,Synthetic pen,12\n"}}}},
              description="Accept raw UTF-8 CSV, maximum 262144 bytes and 1000 records. CSV validity is checked by the worker. Replay the same key and exact bytes to retrieve the same job, including after it is terminal.")
    async def submit_import(request: Request, response: Response, tenant_id: Tenant,
                            idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]):
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise APIError(400, "invalid_idempotency_key", "Use 1..80 ASCII letters, digits, period, underscore, colon, or hyphen; first character must be alphanumeric")
        content_type = request.headers.get("content-type", "").lower().replace(" ", "")
        if content_type not in ("text/csv", "text/csv;charset=utf-8") or request.headers.get("content-encoding", "identity").lower() != "identity":
            raise APIError(415, "unsupported_media_type", "Send uncompressed text/csv with UTF-8 encoding")
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdigit():
                raise APIError(400, "invalid_content_length", "Content-Length must be a nonnegative integer")
            if int(length) > MAX_BYTES:
                raise APIError(413, "payload_too_large", "CSV exceeds 262144 bytes")
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise APIError(413, "payload_too_large", "CSV exceeds 262144 bytes")
                    body.extend(chunk)
        except TimeoutError:
            raise APIError(400, "body_timeout", "CSV body did not finish within 10 seconds") from None
        if not body:
            raise APIError(400, "empty_body", "CSV body is required")
        job, replay = await run_in_threadpool(store.submit, settings, tenant_id, idempotency_key, bytes(body))
        response.headers["Location"] = f"/v1/imports/{job['id']}"
        response.headers["X-Idempotent-Replay"] = str(replay).lower()
        return job

    @app.get("/v1/imports", response_model=models.JobPage, tags=["Imports"])
    def imports(tenant_id: Tenant, after: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
        return store.list_jobs(settings, tenant_id, after, limit)

    @app.get("/v1/imports/{job_id}", response_model=models.Job, tags=["Imports"])
    def import_detail(job_id: UUID, tenant_id: Tenant):
        return store.get_job(settings, tenant_id, job_id)

    @app.post("/v1/imports/{job_id}/cancel", response_model=models.Job, tags=["Imports"], description="Cancel QUEUED/RUNNING under a row lock. If apply committed first, return 409. A cancelled worker token cannot publish.")
    def cancel_import(job_id: UUID, tenant_id: Tenant):
        return store.cancel(settings, tenant_id, job_id)

    @app.get("/v1/imports/{job_id}/errors", response_model=models.ErrorReport, tags=["Imports"])
    def errors(job_id: UUID, tenant_id: Tenant):
        return store.error_report(settings, tenant_id, job_id)

    @app.get("/v1/imports/{job_id}/events", response_model=models.EventPage, tags=["Imports"])
    def events(job_id: UUID, tenant_id: Tenant):
        return store.list_events(settings, tenant_id, job_id)

    @app.get("/v1/records", response_model=models.RecordPage, tags=["Records"], description="Current records sorted by ASCII SKU. Cursor traversal is stable for existing keys; it is not a database snapshot across requests.")
    def records(tenant_id: Tenant, after: Annotated[str, Query(max_length=32, pattern=r"^$|^[A-Z0-9][A-Z0-9_-]{0,31}$")] = "", limit: Annotated[int, Query(ge=1, le=100)] = 20):
        return store.list_records(settings, tenant_id, after, limit)

    return app
