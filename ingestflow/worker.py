import argparse
import signal
import threading
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .config import Settings
from .db import connect
from .store import event
from .validation import Validation, validate_csv


def claim(settings: Settings) -> dict | None:
    with connect(settings) as conn:
        expired = conn.execute(
            "SELECT id,tenant_id,attempts FROM imports WHERE status='RUNNING' AND lease_until<clock_timestamp() ORDER BY lease_until LIMIT 50 FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for row in expired:
            exhausted = row["attempts"] >= 3
            conn.execute(
                "UPDATE imports SET status=%s,lease_token=NULL,lease_until=NULL,failure_code=%s,updated_at=clock_timestamp() WHERE id=%s",
                ("FAILED" if exhausted else "QUEUED", "lease_attempts_exhausted" if exhausted else None, row["id"]),
            )
            event(conn, row["tenant_id"], row["id"], "LEASE_EXPIRED", {"attempt": row["attempts"]})
            if exhausted:
                event(conn, row["tenant_id"], row["id"], "FAILED", {"code": "lease_attempts_exhausted"})
        row = conn.execute("SELECT id FROM imports WHERE status='QUEUED' ORDER BY seq LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not row:
            return None
        token = uuid4()
        job = conn.execute(
            "UPDATE imports SET status='RUNNING',attempts=attempts+1,lease_token=%s,lease_until=clock_timestamp()+(%s*interval '1 second'),updated_at=clock_timestamp() WHERE id=%s RETURNING id,tenant_id,payload,lease_token,attempts",
            (token, settings.lease_seconds, row["id"]),
        ).fetchone()
        event(conn, job["tenant_id"], job["id"], "CLAIMED", {"attempt": job["attempts"]})
        return job


def complete(settings: Settings, job: dict, validation: Validation, fail_after_first_write: bool = False) -> bool:
    with connect(settings) as conn:
        current = conn.execute(
            "SELECT status,lease_token,lease_until FROM imports WHERE id=%s AND tenant_id=%s FOR UPDATE",
            (job["id"], job["tenant_id"]),
        ).fetchone()
        # A cancelled, expired, or re-claimed job cannot publish with its old token.
        if not current or current["status"] != "RUNNING" or current["lease_token"] != job["lease_token"]:
            return False
        lease_valid = conn.execute("SELECT %s::timestamptz > clock_timestamp() AS valid", (current["lease_until"],)).fetchone()["valid"]
        if not lease_valid:
            return False
        if validation.error_count:
            conn.execute(
                "UPDATE imports SET status='FAILED',failure_code='csv_validation_failed',row_count=%s,error_count=%s,errors=%s,lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE id=%s",
                (validation.row_count, validation.error_count, Jsonb(validation.errors), job["id"]),
            )
            event(conn, job["tenant_id"], job["id"], "FAILED", {"code": "csv_validation_failed", "error_count": validation.error_count})
            return True
        for index, product in enumerate(sorted(validation.rows, key=lambda p: p.sku)):
            conn.execute(
                "INSERT INTO records(tenant_id,sku,name,quantity,source_import_id) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,sku) DO UPDATE SET name=EXCLUDED.name,quantity=EXCLUDED.quantity,source_import_id=EXCLUDED.source_import_id,updated_at=clock_timestamp()",
                (job["tenant_id"], product.sku, product.name, product.quantity, job["id"]),
            )
            if fail_after_first_write and index == 0:
                raise RuntimeError("internal test failpoint")
        conn.execute(
            "UPDATE imports SET status='SUCCEEDED',row_count=%s,applied_count=%s,lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE id=%s",
            (validation.row_count, len(validation.rows), job["id"]),
        )
        event(conn, job["tenant_id"], job["id"], "SUCCEEDED", {"applied_count": len(validation.rows)})
        return True


def run_once(settings: Settings) -> bool:
    job = claim(settings)
    if job is None:
        return False
    complete(settings, job, validate_csv(bytes(job["payload"])))
    return True


def main():
    parser = argparse.ArgumentParser(description="Process durable CSV imports")
    parser.add_argument("--once", action="store_true", help="Attempt one claim and exit")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.once:
        run_once(settings)
        return
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            worked = run_once(settings)
        except Exception:
            # Do not log CSV bytes, credentials, SQL parameters, or connection strings.
            print("worker attempt failed; uncommitted work will be recovered after its lease", flush=True)
            worked = False
        if not worked:
            stopped.wait(1)


if __name__ == "__main__":
    main()
