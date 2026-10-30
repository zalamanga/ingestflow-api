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

## Remote PostgreSQL and container execution

The [execution log for job 124219971369](https://github.com/zalamanga/ingestflow-api/actions/runs/41101722993/job/124219971369) was inspected directly through the GitHub job-logs endpoint. It identifies source commit `c860e7a90b261b5c3f9b5a6fb8fb142db91d68c4` and an Ubuntu 26.04 hosted runner. Execution ran from 30 October 2026 17:49 UTC to 17:50 UTC, corresponding to 31 October in Bangkok.

| Check | Observed result in the remote log |
|---|---|
| Runtime and test Docker builds | Images built successfully |
| Isolated PostgreSQL | `ingestflow-test-db-1` healthy |
| Full pytest suite | **25 passed, 1 warning in 3.47 seconds** |
| Actual PostgreSQL scenarios | All 16 database tests passed, including duplicate admission concurrency, concurrent claims, cancellation race, whole-file rejection, bounded persisted errors, stale token fencing, three-claim cap and rollback |
| Killed worker recovery | The subprocess-kill test passed after its durable claim, lease expiry and recovery assertions |
| Runtime startup | Migration completed; API container became healthy with the nonroot/read-only Compose configuration |
| Separate API and worker HTTP probe | Passed: `202` acceptance, replay of the same ID, conflicting bytes `409`, cross-tenant ID `404`, final `SUCCEEDED`, one applied record |
| OpenAPI snapshot | Generated container schema equalled the checked-in JSON |
| Teardown | App and test services stopped; job cleanup reached the end of its log |

There are 25 distinct tests: 9 pure/contract tests and 16 PostgreSQL tests. The Windows run repeated the same 9 pure/contract tests; it does not add 9 new test cases.

The remote probe printed this sanitized result:

```json
{"probe":"actual-http-worker","status":"passed","accepted":202,"replayed_same_id":true,"conflict":409,"cross_tenant":404,"worker_status":"SUCCEEDED","applied_count":1}
```

The runtime image was exported only after these checks. [Artifact `ingestflow-runtime-image`, ID 12998338459](https://github.com/zalamanga/ingestflow-api/actions/runs/41101722993/artifacts/12998338459) was uploaded with ZIP size 55367169 bytes and uploaded-ZIP SHA-256 `326b909bdfae1ea6a2dd64f84a5066bef58a7ca6e00c2076179a547ab4cc04cd`. Artifacts expire after three days; building from the source remains the durable path.

At inspection, GitHub run/check metadata still reported `queued` despite the complete direct execution log and uploaded artifact. The results above are grounded in the recorded commands, assertions and output, rather than that stale metadata or a claim that a workflow file alone proves execution.

No local Docker build or database was started for these remote checks. The published runtime image excludes `.env`, local credentials, local caches and test-only crash helpers by its build context and target. Final repository publication and secret review are handled separately from this test execution record.


## OpenAPI reference image

On 31 October 2026 local time, Swagger Parser 12.1.0 validated the committed OpenAPI 3.1.0 contract (8 method/route operations). Its SHA-256 was `840c572af2630046cd696e0e2cdbe8c24602a0ee1519a6a129d80101c1ee8078`.

The [reference image](screenshots/openapi-reference.png) is a real 1440 x 1100 browser capture of that contract rendered by Swagger UI 5.34.1, with no JavaScript page errors. It displays documented endpoints; it is not an application dashboard or evidence of live API responses. No credentials were entered into the renderer. Runtime and database evidence remains separate above.
