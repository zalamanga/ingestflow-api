CREATE TABLE tenants (
    id text PRIMARY KEY CHECK (id IN ('alpha', 'beta'))
);
INSERT INTO tenants(id) VALUES ('alpha'), ('beta');

CREATE TABLE imports (
    seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 80),
    payload_sha256 char(64) NOT NULL,
    payload bytea NOT NULL CHECK (octet_length(payload) BETWEEN 1 AND 262144),
    status text NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    lease_token uuid,
    lease_until timestamptz,
    row_count integer NOT NULL DEFAULT 0 CHECK (row_count BETWEEN 0 AND 1001),
    applied_count integer NOT NULL DEFAULT 0 CHECK (applied_count BETWEEN 0 AND 1000),
    error_count integer NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    errors jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(errors) = 'array' AND jsonb_array_length(errors) <= 50),
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, id),
    CHECK ((status = 'RUNNING' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND attempts >= 1)
        OR (status <> 'RUNNING' AND lease_token IS NULL AND lease_until IS NULL))
);
CREATE INDEX imports_queue ON imports(seq) WHERE status = 'QUEUED';
CREATE INDEX imports_expired ON imports(lease_until) WHERE status = 'RUNNING';
CREATE INDEX imports_tenant_page ON imports(tenant_id, seq);

CREATE TABLE records (
    tenant_id text NOT NULL REFERENCES tenants(id),
    sku text COLLATE "C" NOT NULL CHECK (sku ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'),
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 100),
    quantity integer NOT NULL CHECK (quantity BETWEEN 0 AND 999999),
    source_import_id uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, sku),
    FOREIGN KEY (tenant_id, source_import_id) REFERENCES imports(tenant_id, id)
);

CREATE TABLE import_events (
    seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id text NOT NULL,
    import_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('QUEUED','CLAIMED','LEASE_EXPIRED','SUCCEEDED','FAILED','CANCELLED')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, import_id) REFERENCES imports(tenant_id, id)
);
CREATE INDEX events_job ON import_events(tenant_id, import_id, seq);
