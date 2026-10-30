from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import UUID

import pytest

from ingestflow import store
from ingestflow.db import connect, migrate
from ingestflow.errors import APIError
from ingestflow.validation import validate_csv
from ingestflow.worker import claim, complete, run_once
from tests.conftest import ALPHA, BETA

VALID = b"sku,name,quantity\nPEN-001,Synthetic pen,12\nBOOK-001,Synthetic notebook,4\n"


def enqueue(settings, key="demo", payload=VALID, tenant="alpha"):
    result, _ = store.submit(settings, tenant, key, payload)
    return UUID(result["id"])


def test_migration_is_repeatable(settings):
    migrate(settings)
    with connect(settings) as conn:
        assert conn.execute("SELECT count(*) AS n FROM tenants").fetchone()["n"] == 2


def test_import_success_and_upsert_are_visible(settings):
    job_id = enqueue(settings)
    assert run_once(settings)
    job = store.get_job(settings, "alpha", job_id)
    assert job["status"] == "SUCCEEDED" and job["applied_count"] == 2
    enqueue(settings, "update", b"sku,name,quantity\nPEN-001,Updated synthetic pen,20\n")
    assert run_once(settings)
    records = store.list_records(settings, "alpha", "", 100)["items"]
    assert len(records) == 2 and records[1]["quantity"] == 20


def test_invalid_csv_writes_no_products(settings):
    job_id = enqueue(settings, payload=b"sku,name,quantity\nPEN-001,Valid row,1\nBAD,Invalid row,-1\n")
    assert run_once(settings)
    job = store.get_job(settings, "alpha", job_id)
    assert job["status"] == "FAILED" and job["applied_count"] == 0
    assert store.list_records(settings, "alpha", "", 100)["items"] == []
    assert store.error_report(settings, "alpha", job_id)["errors"][0]["row"] == 3


def test_mixed_error_report_is_persisted_and_bounded(settings):
    job_id = enqueue(settings, payload=b"sku,name,quantity\n" + b"bad sku, ,NaN\n" * 100)
    assert run_once(settings)
    report = store.error_report(settings, "alpha", job_id)
    assert report["status"] == "FAILED" and report["error_count"] >= 300
    assert len(report["errors"]) == 50 and report["truncated"] is True
    assert store.list_records(settings, "alpha", "", 100)["items"] == []


def test_duplicate_idempotency_concurrency_creates_one_job(settings):
    barrier = threading.Barrier(6)
    def submit():
        barrier.wait()
        return store.submit(settings, "alpha", "same", VALID)
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: submit(), range(6)))
    assert len({row["id"] for row, _ in results}) == 1
    assert sum(not replay for _, replay in results) == 1
    with connect(settings) as conn:
        assert conn.execute("SELECT count(*) AS n FROM imports").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM import_events WHERE kind='QUEUED'").fetchone()["n"] == 1
    with pytest.raises(APIError) as conflict:
        store.submit(settings, "alpha", "same", VALID + b"\n")
    assert conflict.value.status == 409


def test_two_workers_claim_distinct_jobs(settings):
    for n in range(2):
        enqueue(settings, str(n))
    barrier = threading.Barrier(2)
    def take():
        barrier.wait()
        return claim(settings)
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda _: take(), range(2)))
    assert jobs[0]["id"] != jobs[1]["id"]
    assert {j["attempts"] for j in jobs} == {1}


def test_tenant_boundaries_cover_jobs_errors_events_records(client, settings):
    alpha = {"Authorization": f"Bearer {ALPHA}", "Content-Type": "text/csv", "Idempotency-Key": "boundary"}
    beta = {"Authorization": f"Bearer {BETA}"}
    response = client.post("/v1/imports", content=VALID, headers=alpha)
    assert response.status_code == 202
    job_id = response.json()["id"]
    for suffix in ("", "/errors", "/events"):
        assert client.get(f"/v1/imports/{job_id}{suffix}", headers=beta).status_code == 404
    assert client.post(f"/v1/imports/{job_id}/cancel", headers=beta).status_code == 404
    run_once(settings)
    assert client.get("/v1/records", headers=beta).json()["items"] == []
    assert client.get("/v1/imports", headers=beta).json()["items"] == []
    replay, first = store.submit(settings, "beta", "boundary", VALID)
    assert first is False and replay["id"] != job_id


def test_cancel_wins_before_apply(settings):
    job_id = enqueue(settings)
    job = claim(settings)
    assert store.cancel(settings, "alpha", job_id)["status"] == "CANCELLED"
    assert complete(settings, job, validate_csv(VALID)) is False
    assert store.list_records(settings, "alpha", "", 100)["items"] == []


def test_apply_wins_before_cancel(settings):
    job_id = enqueue(settings)
    assert run_once(settings)
    with pytest.raises(APIError) as error:
        store.cancel(settings, "alpha", job_id)
    assert error.value.status == 409
    assert store.get_job(settings, "alpha", job_id)["status"] == "SUCCEEDED"


def test_cancellation_racing_with_apply_has_one_terminal_outcome(settings):
    job_id = enqueue(settings)
    job = claim(settings)
    barrier = threading.Barrier(2)
    def apply():
        barrier.wait()
        return complete(settings, job, validate_csv(VALID))
    def cancel():
        barrier.wait()
        try:
            return store.cancel(settings, "alpha", job_id)["status"]
        except APIError as error:
            assert error.status == 409
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        applied = executor.submit(apply)
        cancelled = executor.submit(cancel)
        result = applied.result()
        cancel_result = cancelled.result()
    final = store.get_job(settings, "alpha", job_id)["status"]
    records = store.list_records(settings, "alpha", "", 100)["items"]
    if final == "SUCCEEDED":
        assert result is True and cancel_result == "conflict" and len(records) == 2
    else:
        assert final == "CANCELLED" and result is False and cancel_result == "CANCELLED" and records == []
    terminal_events = [e for e in store.list_events(settings, "alpha", job_id)["items"] if e["kind"] in ("SUCCEEDED", "CANCELLED")]
    assert len(terminal_events) == 1


def test_admission_cap_preserves_idempotent_replay(settings, monkeypatch):
    monkeypatch.setattr(store, "MAX_ACTIVE", 1)
    original = enqueue(settings)
    replay, was_replay = store.submit(settings, "alpha", "demo", VALID)
    assert was_replay and replay["id"] == str(original)
    with pytest.raises(APIError) as error:
        enqueue(settings, "new")
    assert error.value.code == "import_capacity_reached"


def test_expired_lease_fences_old_worker_and_caps_attempts(settings):
    job_id = enqueue(settings)
    old = claim(settings)
    with connect(settings) as conn:
        conn.execute("UPDATE imports SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job_id,))
    assert complete(settings, old, validate_csv(VALID)) is False
    second = claim(settings)
    assert second["attempts"] == 2 and second["lease_token"] != old["lease_token"]
    assert complete(settings, old, validate_csv(VALID)) is False
    for expected in (3, None):
        with connect(settings) as conn:
            conn.execute("UPDATE imports SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job_id,))
        next_job = claim(settings)
        if expected:
            assert next_job["attempts"] == expected
        else:
            assert next_job is None
    final = store.get_job(settings, "alpha", job_id)
    assert final["status"] == "FAILED" and final["failure_code"] == "lease_attempts_exhausted"
    assert final["attempts"] == 3


def test_transaction_failure_rolls_back_every_effect(settings):
    job_id = enqueue(settings)
    job = claim(settings)
    with pytest.raises(RuntimeError, match="internal test failpoint"):
        complete(settings, job, validate_csv(VALID), fail_after_first_write=True)
    assert store.get_job(settings, "alpha", job_id)["status"] == "RUNNING"
    assert store.list_records(settings, "alpha", "", 100)["items"] == []
    events = store.list_events(settings, "alpha", job_id)["items"]
    assert "SUCCEEDED" not in [e["kind"] for e in events]


def test_job_cursor_has_no_repeats_when_new_jobs_arrive(settings):
    for n in range(3):
        enqueue(settings, str(n))
    first = store.list_jobs(settings, "alpha", 0, 2)
    enqueue(settings, "later")
    second = store.list_jobs(settings, "alpha", first["next_cursor"], 2)
    ids = [j["id"] for j in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 4


def test_http_bounds_and_errors(client):
    headers = {"Authorization": f"Bearer {ALPHA}", "Idempotency-Key": "bounds", "Content-Type": "text/csv"}
    assert client.get("/v1/imports").status_code == 401
    assert client.post("/v1/imports", headers={**headers, "Content-Type": "application/json"}, content=VALID).status_code == 415
    assert client.post("/v1/imports", headers=headers, content=b"x" * 262145).status_code == 413
    assert client.post("/v1/imports", headers=headers, content=b"").status_code == 400
    assert client.post("/v1/imports", headers={**headers, "Idempotency-Key": "bad key"}, content=VALID).status_code == 400
    assert client.get("/v1/imports?limit=0", headers=headers).status_code == 422
    assert client.get("/v1/imports/not-a-uuid", headers=headers).status_code == 422
    response = client.post("/v1/imports", headers=headers, content=VALID)
    assert response.status_code == 202 and response.headers["location"].endswith(response.json()["id"])
    replay = client.post("/v1/imports", headers=headers, content=VALID)
    assert replay.status_code == 202 and replay.headers["x-idempotent-replay"] == "true"
    assert replay.json()["id"] == response.json()["id"]


def test_subprocess_sigkill_after_durable_claim_recovers(settings, tmp_path):
    job_id = enqueue(settings, "crash")
    marker = tmp_path / "claimed.txt"
    env = {
        **os.environ, "DATABASE_URL": settings.database_url,
        "TENANT_ALPHA_KEY_SHA256": settings.alpha_digest,
        "TENANT_BETA_KEY_SHA256": settings.beta_digest,
        "INGESTFLOW_SCHEMA": settings.schema, "LEASE_SECONDS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    child = subprocess.Popen([sys.executable, "-m", "tests.claim_and_pause", str(marker)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < deadline:
            assert child.poll() is None, "Probe process exited before its durable claim"
            time.sleep(0.05)
        assert marker.exists(), "Probe did not signal its claim"
        assert marker.read_text(encoding="ascii") == str(job_id)
        assert store.get_job(settings, "alpha", job_id)["status"] == "RUNNING"
        assert store.list_records(settings, "alpha", "", 100)["items"] == []
        child.kill()  # SIGKILL on Linux CI; TerminateProcess on Windows.
        child.wait(timeout=10)
        assert child.returncode != 0
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connect(settings) as conn:
                expired = conn.execute("SELECT lease_until<clock_timestamp() AS expired FROM imports WHERE id=%s", (job_id,)).fetchone()["expired"]
            if expired:
                break
            time.sleep(0.05)
        assert expired
        assert run_once(settings)
        final = store.get_job(settings, "alpha", job_id)
        assert final["status"] == "SUCCEEDED" and final["attempts"] == 2 and final["applied_count"] == 2
        assert len(store.list_records(settings, "alpha", "", 100)["items"]) == 2
        kinds = [e["kind"] for e in store.list_events(settings, "alpha", job_id)["items"]]
        assert kinds.count("CLAIMED") == 2 and kinds.count("LEASE_EXPIRED") == 1 and kinds.count("SUCCEEDED") == 1
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
