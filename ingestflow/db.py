from contextlib import contextmanager
import hashlib
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import Settings


@contextmanager
def connect(settings: Settings):
    with psycopg.connect(
        settings.database_url,
        connect_timeout=5,
        options=f"-c search_path={settings.schema} -c statement_timeout=10000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=15000",
        row_factory=dict_row,
    ) as conn:
        yield conn


def migrate(settings: Settings):
    source = (Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql").read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode()).hexdigest()
    with connect(settings) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(71001901)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, sha256 text NOT NULL)")
        row = conn.execute("SELECT sha256 FROM schema_migrations WHERE version = 1").fetchone()
        if row:
            if row["sha256"] != digest:
                raise RuntimeError("Migration checksum changed; create a new migration")
            return
        conn.execute(source)
        conn.execute("INSERT INTO schema_migrations(version, sha256) VALUES (1, %s)", (digest,))
