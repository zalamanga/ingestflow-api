import hashlib
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .config import Settings
from .db import connect
from .errors import APIError

JOB_COLUMNS = "id, seq, status, attempts, row_count, applied_count, error_count, failure_code, created_at, updated_at"
MAX_RETAINED = 200
MAX_ACTIVE = 50


def job_view(row: dict) -> dict:
    return {
        "id": str(row["id"]), "sequence": row["seq"], "status": row["status"],
        "attempts": row["attempts"], "row_count": row["row_count"],
        "applied_count": row["applied_count"], "error_count": row["error_count"],
        "failure_code": row["failure_code"], "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def event(conn, tenant: str, job_id: UUID, kind: str, details: dict | None = None):
    conn.execute(
        "INSERT INTO import_events(tenant_id, import_id, kind, details) VALUES (%s,%s,%s,%s)",
        (tenant, job_id, kind, Jsonb(details or {})),
    )


def submit(settings: Settings, tenant: str, key: str, payload: bytes) -> tuple[dict, bool]:
    digest = hashlib.sha256(tenant.encode("ascii") + b"\x00" + payload).hexdigest()
    with connect(settings) as conn:
        # Serializes admission and the idempotency check for this bounded tenant queue.
        conn.execute("SELECT id FROM tenants WHERE id=%s FOR UPDATE", (tenant,))
        existing = conn.execute(
            f"SELECT {JOB_COLUMNS}, payload_sha256 FROM imports WHERE tenant_id=%s AND idempotency_key=%s",
            (tenant, key),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise APIError(409, "idempotency_conflict", "This key was already used with different CSV bytes")
            return job_view(existing), True
        counts = conn.execute(
            "SELECT count(*) AS total, count(*) FILTER (WHERE status IN ('QUEUED','RUNNING')) AS active FROM imports WHERE tenant_id=%s",
            (tenant,),
        ).fetchone()
        if counts["total"] >= MAX_RETAINED or counts["active"] >= MAX_ACTIVE:
            raise APIError(409, "import_capacity_reached", "Tenant import capacity reached; retained jobs are not automatically deleted")
        job_id = uuid4()
        row = conn.execute(
            f"INSERT INTO imports(id,tenant_id,idempotency_key,payload_sha256,payload) VALUES (%s,%s,%s,%s,%s) RETURNING {JOB_COLUMNS}",
            (job_id, tenant, key, digest, payload),
        ).fetchone()
        event(conn, tenant, job_id, "QUEUED", {"bytes": len(payload)})
        return job_view(row), False


def get_job(settings: Settings, tenant: str, job_id: UUID) -> dict:
    with connect(settings) as conn:
        row = conn.execute(f"SELECT {JOB_COLUMNS} FROM imports WHERE tenant_id=%s AND id=%s", (tenant, job_id)).fetchone()
        if not row:
            raise APIError(404, "import_not_found", "Import not found")
        return job_view(row)


def list_jobs(settings: Settings, tenant: str, after: int, limit: int) -> dict:
    with connect(settings) as conn:
        rows = conn.execute(
            f"SELECT {JOB_COLUMNS} FROM imports WHERE tenant_id=%s AND seq>%s ORDER BY seq LIMIT %s",
            (tenant, after, limit + 1),
        ).fetchall()
        page = rows[:limit]
        return {"items": [job_view(row) for row in page], "next_cursor": page[-1]["seq"] if len(rows) > limit else None}


def cancel(settings: Settings, tenant: str, job_id: UUID) -> dict:
    with connect(settings) as conn:
        row = conn.execute("SELECT status FROM imports WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant, job_id)).fetchone()
        if not row:
            raise APIError(404, "import_not_found", "Import not found")
        if row["status"] not in ("QUEUED", "RUNNING"):
            raise APIError(409, "import_already_terminal", "A terminal import cannot be cancelled")
        row = conn.execute(
            f"UPDATE imports SET status='CANCELLED',lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE id=%s RETURNING {JOB_COLUMNS}",
            (job_id,),
        ).fetchone()
        event(conn, tenant, job_id, "CANCELLED")
        return job_view(row)


def error_report(settings: Settings, tenant: str, job_id: UUID) -> dict:
    with connect(settings) as conn:
        row = conn.execute("SELECT status,error_count,errors,failure_code FROM imports WHERE tenant_id=%s AND id=%s", (tenant, job_id)).fetchone()
        if not row:
            raise APIError(404, "import_not_found", "Import not found")
        return {"import_id": str(job_id), "status": row["status"], "failure_code": row["failure_code"], "error_count": row["error_count"], "errors": row["errors"], "truncated": row["error_count"] > len(row["errors"])}


def list_events(settings: Settings, tenant: str, job_id: UUID) -> dict:
    get_job(settings, tenant, job_id)
    with connect(settings) as conn:
        rows = conn.execute("SELECT seq,kind,details,created_at FROM import_events WHERE tenant_id=%s AND import_id=%s ORDER BY seq LIMIT 20", (tenant, job_id)).fetchall()
        return {"items": rows}


def list_records(settings: Settings, tenant: str, after: str, limit: int) -> dict:
    with connect(settings) as conn:
        rows = conn.execute(
            'SELECT sku,name,quantity,source_import_id,updated_at FROM records WHERE tenant_id=%s AND sku>%s COLLATE "C" ORDER BY sku LIMIT %s',
            (tenant, after, limit + 1),
        ).fetchall()
        page = rows[:limit]
        return {"items": page, "next_cursor": page[-1]["sku"] if len(rows) > limit else None}
