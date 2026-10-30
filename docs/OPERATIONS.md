# Local operation and verification

## Requirements and storage

Use Docker Desktop with Linux containers, Docker Compose v2 supporting `up --wait`, PowerShell, and Python 3.13. Runtime application dependencies live in Docker. `Init.ps1` uses only the Python standard library; it does not install packages globally.

Keep the repository on D: if that is your development drive. PowerShell wrappers redirect `TEMP`, `TMP`, pip cache and Python bytecode cache to `.local/`, then restore their previous values. Docker image/build/volume storage follows Docker Desktop's own disk-image setting; moving a repository does not move Docker's virtual disk.

Run one project's builds/tests at a time on an 8 GB machine. The app database is limited to 256 MiB, API and worker to 192 MiB each. Test database and test process are each limited to 256 MiB. Limits are configuration bounds, not measured typical consumption.

## Start and stop

```powershell
.\scripts\Init.ps1
.\scripts\Start.ps1
.\scripts\Start.ps1 -NoBuild   # Reuse an already-built local image
.\scripts\Stop.ps1
```

Compose project `ingestflow` contains `db`, one-off `migrate`, `api`, and `worker`. Migration takes a transaction-scoped advisory lock and records the source checksum. Changing an already-applied migration produces an error instead of silently rewriting database history.

`Stop.ps1` uses `docker compose -f compose.yml -p ingestflow down --remove-orphans`. It preserves the `ingestflow_ingestflow_pgdata` volume. It does not stop other projects or delete Docker images. Do not add `--volumes` unless you deliberately want to erase this demo database.

The API listens on loopback port 8100. PostgreSQL listens on loopback port 5454. If either is already used, inspect the owner; do not stop an unrelated process just to free the port. Keep `.env` consistent with an existing PostgreSQL volume: changing `POSTGRES_PASSWORD` does not change an already-initialized database user's password.

## Demo credentials

`scripts/init_env.py` creates three independent random 64-hex values: database password, alpha key, beta key. It derives the two SHA-256 key digests and writes private `.env` plus `.local/LOCAL-CREDENTIALS.txt`. It does not print key values. Existing valid values are preserved and mismatched digests fail for manual review.

Open the credentials text file locally when using Swagger or Postman. Only its raw tenant key belongs in the Swagger Authorize input. The API receives the two digests, not the original tenant keys. There is no administrative login or password recovery route in this demo.

Never publish local credentials, copy real inventory data into examples, or screenshot an authorized Swagger dialog. Postman's checked-in variable values are placeholders. Do not run `docker compose config` without `--quiet` in shared logs because resolved database connection strings include the private database password.

## Run tests

```powershell
.\scripts\Test.ps1
.\scripts\Test.ps1 -NoBuild
```

The wrapper refuses to use an occupied port 5455, generates a temporary test password, builds the test Docker target, starts an isolated PostgreSQL database named `ingestflow_test`, runs pytest, and tears down only `ingestflow-test` services. Test PostgreSQL uses tmpfs, so teardown discards test data. The test image contains internal failpoint/crash helpers that the runtime target does not copy.

Every PostgreSQL test creates a unique `test_<32 hex>` schema and drops it afterward. The suite refuses database URLs whose database name is not exactly `ingestflow_test`. Missing PostgreSQL is a failure; these tests do not silently skip database coverage. Keep test and app database credentials separate.

Tests cover CSV validation bounds, replay concurrency, two concurrent workers, tenant boundaries, cancellation both before/after apply plus an actual racing cancellation, stale lease tokens, the three-claim cap, atomic rollback after the first record write, pagination and HTTP errors, and subprocess crash recovery. See `docs/VERIFICATION.md` for execution evidence.

For native development, create a project-local virtualenv and redirect caches before installation. Start only the isolated test database, set `INGESTFLOW_TEST_DB_URL`, then run:

```powershell
python -m pytest --basetemp=.local/pytest -p no:cacheprovider
python -m scripts.export_openapi
```

Do not point tests at the application database. The native command needs `requirements-dev.txt` installed in that local virtualenv. `Test.ps1` handles this through Docker instead.

## Verify the real HTTP API

`scripts/smoke.py` is a standard-library client for an already-running API and separate worker. It checks unauthorized access, acceptance, replay, conflict, cross-tenant isolation, committed record effects, and terminal cancellation. It reads private keys only from process environment and prints a sanitized result object.

The CI workflow passes keys by environment to the test image, on the local Compose network. It does not expose a test-only HTTP route or use external services. The smoke probe writes one synthetic `SMOKE-001` record; each invocation consumes one retained job. It is a verification tool, not a read-only health check.

## Inspect without exposing data

```powershell
docker compose -f compose.yml -p ingestflow ps
docker compose -f compose.yml -p ingestflow logs --tail 40 api worker migrate
docker compose -f compose.yml -p ingestflow exec db psql -U ingestflow -d ingestflow -c "SELECT status,count(*) FROM imports GROUP BY status;"
```

API access logs are disabled. Worker failure logging uses a fixed message and does not print database errors, SQL parameters, CSV data, or credentials. PostgreSQL administrators can still read payloads directly, so the volume is not a secrecy boundary against the host owner.

## Troubleshooting

`401`: confirm you used the alpha/beta raw key from this repository's `.local` file, not the digest or database password. `409 idempotency_conflict`: reuse the original bytes or use a fresh key for a new file. `FAILED csv_validation_failed`: inspect `/errors`; original field values are deliberately not included. `FAILED lease_attempts_exhausted`: inspect worker health/resource pressure before submitting a new job.

A `RUNNING` import after a forced worker stop is expected until its lease expires. Restart the worker to recover it. Do not manually change a production job's status to bypass fencing. There is no heartbeat, so validation that exceeds its lease will be rejected at apply and retried.

`503`: database connection/statement/lock timeouts return a sanitized retryable error. The client may not know whether a previous submission committed. Retry the same key and exact CSV bytes. Do not automatically invent a new key after an uncertain response.

The retained-job cap intentionally stops new work at 200 jobs per tenant. This demo has no destructive purge endpoint. For a fresh disposable environment, use a separately named database/volume or deliberately remove only this project's volume after reviewing the data you are discarding.
