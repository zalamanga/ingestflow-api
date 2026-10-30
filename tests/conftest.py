import hashlib
import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest
from fastapi.testclient import TestClient

from ingestflow.api import create_app
from ingestflow.config import Settings
from ingestflow.db import migrate

ALPHA = "a" * 64
BETA = "b" * 64


@pytest.fixture
def settings():
    dsn = os.environ.get("INGESTFLOW_TEST_DB_URL", "")
    if not dsn or conninfo_to_dict(dsn).get("dbname") != "ingestflow_test":
        pytest.fail("Set INGESTFLOW_TEST_DB_URL to an isolated PostgreSQL database named ingestflow_test; database tests are never skipped")
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "ingestflow_test"
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    config = Settings(dsn, hashlib.sha256(ALPHA.encode()).hexdigest(), hashlib.sha256(BETA.encode()).hexdigest(), schema=schema)
    migrate(config)
    try:
        yield config
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as http:
        yield http
