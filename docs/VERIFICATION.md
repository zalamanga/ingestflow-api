# Verification status

Native Windows checks on 31 October 2026 used Python 3.13 and a private virtualenv under this repository's `.local/venv`. `TEMP`, `TMP`, pip cache and Python bytecode cache were directed under the same project's `.local/`, then restored.

| Check | Observed result |
|---|---|
| Binary-only pinned dependency installation | Passed; no native compiler invoked |
| `pip check` | Passed, no broken requirements |
| `pytest tests/test_validation.py tests/test_contract.py --basetemp=.local/pytest -p no:cacheprovider` | 9 passed in 5.66 seconds |
| Python AST parsing | 20 source files parsed |
| Postman collection | JSON parsed |
| PowerShell scripts | Parser reported no errors |
| Generated OpenAPI | 34583 bytes; snapshot equality test passed |

OpenAPI SHA-256: `840c572af2630046cd696e0e2cdbe8c24602a0ee1519a6a129d80101c1ee8078`.

The native test run emitted one upstream deprecation warning: Starlette 1.10 retains its working HTTPX compatibility client but recommends HTTPX2 for future migration. The existing HTTPX 0.28.1 pin passed these tests. This warning was not suppressed.

25 test functions are authored: 9 pure/contract tests and 16 actual PostgreSQL tests. PostgreSQL, container startup, worker crash recovery and real HTTP probe are still pending coordinated execution. The test count is not presented as a passing integration result.

Remaining checks:

- Actual PostgreSQL integration tests, including concurrent submission/claims and cancellation.
- Subprocess crash after a durable claim, deadline expiry, recovery, one success event and expected record effects.
- Container runtime startup with nonroot/read-only settings.
- Real HTTP smoke against API and separate worker, including tenant boundary and conflicting replay.
- Final secret review excludes `.env`, private keys, payload logs, local caches and credentials from Git.

The repository's workflow runs PostgreSQL, concurrency, crash-recovery, OpenAPI and HTTP checks. A workflow file existing does not establish that a workflow run has passed.
