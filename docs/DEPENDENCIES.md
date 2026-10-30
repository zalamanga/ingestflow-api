# Dependency sources

Versions were checked against the primary PyPI package JSON and existing compatible local manifests on 31 October 2026. This is a version provenance note, not a vulnerability audit or performance result.

| Package | Pin | Primary source |
|---|---|---|
| FastAPI | 0.162.0 | https://pypi.org/project/fastapi/0.162.0/ |
| Uvicorn | 0.54.0 | https://pypi.org/project/uvicorn/0.54.0/ |
| Psycopg / binary | 3.3.6 | https://pypi.org/project/psycopg/3.3.6/ |
| pytest | 9.2.0 | https://pypi.org/project/pytest/9.2.0/ |
| HTTPX | 0.28.1 | https://pypi.org/project/httpx/0.28.1/ |

Runtime transitive pins reuse the compatible FastAPI/Pydantic/Psycopg version set in the existing local Python project manifests. No code, credentials or database files were copied from those projects. Docker base images use the official `python:3.13-slim-bookworm` and `postgres:17-bookworm` tags; these tags are not immutable image digests.

Relevant behavior references: [Psycopg connection contexts and transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html), [PostgreSQL SELECT locking clauses](https://www.postgresql.org/docs/17/sql-select.html#SQL-FOR-UPDATE-SHARE), and [Python CSV parser](https://docs.python.org/3.13/library/csv.html).
