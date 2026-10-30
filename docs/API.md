# API contract

Base URL: `http://127.0.0.1:8100`. Routes below `/v1` require an `Authorization: Bearer <private-key>` header. Requests without a valid key return `401` with `WWW-Authenticate: Bearer`. Query-string credentials are not supported. CORS is not enabled; use server clients, Postman, or same-origin Swagger UI.

## Submit

`POST /v1/imports` takes raw CSV bytes, not JSON or multipart form data. Send `Content-Type: text/csv` or `text/csv; charset=utf-8`. Compression and other encodings return `415`.

`Idempotency-Key` is mandatory: 1..80 ASCII characters, first alphanumeric, remaining characters alphanumeric or `._:-`. Missing header is `422`; malformed content is `400`. The key belongs to the authenticated tenant. Reusing it with identical bytes returns `202` and the same job, even if the job is now terminal. `X-Idempotent-Replay` says `true` or `false`. Different bytes return `409 idempotency_conflict`.

```csv
sku,name,quantity
PEN-001,Synthetic blue pen,12
NOTEBOOK-001,Synthetic notebook,5
```

The maximum body is 262144 bytes. The streamed body is bounded even when `Content-Length` is missing, and must finish within 10 seconds. An empty body returns `400`; an oversized body returns `413`. Structural CSV validation happens asynchronously. A `202` response means the job was persisted, not that its rows passed validation.

The response body is a job object with `id`, `sequence`, `status`, `attempts`, `row_count`, `applied_count`, `error_count`, `failure_code`, `created_at`, and `updated_at`. Timestamps are database-generated UTC instants. A relative `Location` points to `/v1/imports/{id}`. Job responses do not expose CSV bytes, idempotency keys, worker tokens, or tenant credentials.

## Read and cancel

`GET /v1/imports?after=0&limit=20` returns `{items, next_cursor}`. Feed a non-null sequence cursor back into `after`. Limit is 1..100. Results use ascending sequence order; concurrent new inserts do not shift earlier pages. Identity sequences can have gaps. This is a traversal, not a snapshot across requests.

`GET /v1/imports/{id}` returns a job. Valid UUIDs from another tenant return `404`, including on report, event, and cancellation routes. Invalid UUID syntax returns `422`.

`POST /v1/imports/{id}/cancel` has no request body. It returns the terminal `CANCELLED` job when a queued/running import is cancelled. If a worker already committed its apply transaction, or the job was already failed/cancelled, the route returns `409 import_already_terminal`. Cancellation is deliberately not silently repeated as success.

`GET /v1/imports/{id}/errors` returns `import_id`, `status`, `failure_code`, `error_count`, `errors`, and `truncated`. A row error contains only logical CSV record index, field name, and error code. Original CSV field values are not included. At most 50 entries are retained, although `error_count` counts detected errors until the bounded parser stops at record 1001 or a CSV syntax error.

`GET /v1/imports/{id}/events` returns lifecycle events in ascending sequence order. Each job has a bounded lifecycle of at most three claims, so this endpoint returns at most 20 entries without pagination. Event details contain counts and failure codes, never uploaded field values.

`GET /v1/records?after=PEN-001&limit=20` returns `{items, next_cursor}`. Records use ASCII SKU order and contain name, quantity, source import ID, and update timestamp. No source payload is returned. Existing key traversal does not repeat keys; a newly inserted key behind an already-used cursor will be seen on a new traversal.

## Status and validation codes

Job states: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`. `csv_validation_failed` means no rows were written from that import. `lease_attempts_exhausted` means three claims expired; it does not invent a row validation error.

CSV report codes include `file_too_large`, `invalid_utf8`, `null_byte`, `expected_sku_name_quantity`, `too_many_rows`, `expected_three_columns`, `invalid_sku`, `duplicate_sku`, `invalid_name`, `expected_integer_0_to_999999`, `malformed_csv`, and `empty_import`. UTF-8 BOM and LF/CRLF are accepted. A quoted comma is accepted. A newline within a quoted name is rejected as a control character. Empty lines are not ignored.

| HTTP status | Meaning |
|---|---|
| `200` | Read/cancel succeeded |
| `202` | Job accepted or idempotently replayed |
| `400` | Bad key syntax, empty body, body timeout, invalid content length |
| `401` | Missing/invalid tenant bearer key |
| `404` | Job not found in this tenant |
| `409` | Idempotency conflict, capacity reached, or terminal cancellation |
| `413` | Body exceeds 256 KiB |
| `415` | Unsupported media type/encoding |
| `422` | Header/path/query validation failed |
| `503` | Database request unavailable; retry with the original key and bytes |

Application errors use `{"error":{"code":"...","message":"..."}}`. The ASGI server can also reject malformed HTTP or excessive concurrent connections before the application runs; those transport responses do not share the JSON envelope. No performance or availability SLA is asserted.
