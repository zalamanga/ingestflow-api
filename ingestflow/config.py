from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class Settings:
    database_url: str
    alpha_digest: str
    beta_digest: str
    schema: str = "public"
    lease_seconds: int = 30

    def __post_init__(self):
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        for digest in (self.alpha_digest, self.beta_digest):
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError("Tenant key SHA-256 digests must be 64 lowercase hex characters")
        if self.alpha_digest == self.beta_digest:
            raise ValueError("Tenant keys must differ")
        if not re.fullmatch(r"public|test_[a-f0-9]{32}", self.schema):
            raise ValueError("Invalid database schema")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("Lease duration must be 1..300 seconds")

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            alpha_digest=os.environ.get("TENANT_ALPHA_KEY_SHA256", ""),
            beta_digest=os.environ.get("TENANT_BETA_KEY_SHA256", ""),
            schema=os.environ.get("INGESTFLOW_SCHEMA", "public"),
            lease_seconds=int(os.environ.get("LEASE_SECONDS", "30")),
        )
