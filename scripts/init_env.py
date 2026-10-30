from pathlib import Path
import hashlib
import re
import secrets

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / ".env"
if path.exists():
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Z0-9_]+", key):
                raise SystemExit("Existing .env format is invalid; it has not been overwritten")
            values[key] = value
else:
    values = {key: secrets.token_hex(32) for key in ("POSTGRES_PASSWORD", "TENANT_ALPHA_KEY", "TENANT_BETA_KEY")}
for key in ("POSTGRES_PASSWORD", "TENANT_ALPHA_KEY", "TENANT_BETA_KEY"):
    if not re.fullmatch(r"[a-f0-9]{64}", values.get(key, "")):
        raise SystemExit(f"{key} must contain 64 lowercase hex characters; existing .env was preserved")
if values["TENANT_ALPHA_KEY"] == values["TENANT_BETA_KEY"]:
    raise SystemExit("Tenant keys must differ")
for tenant in ("ALPHA", "BETA"):
    digest = hashlib.sha256(values[f"TENANT_{tenant}_KEY"].encode()).hexdigest()
    digest_key = f"TENANT_{tenant}_KEY_SHA256"
    if digest_key in values and values[digest_key] != digest:
        raise SystemExit("Existing tenant digest does not match its key; review .env before retrying")
    values[digest_key] = digest
path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
local = ROOT / ".local"
local.mkdir(exist_ok=True)
(local / "LOCAL-CREDENTIALS.txt").write_text(
    "Private local demo keys. Do not commit, screenshot, or publish this file.\n"
    "Base URL: http://127.0.0.1:8100\n"
    f"Alpha Authorization: Bearer {values['TENANT_ALPHA_KEY']}\n"
    f"Beta Authorization: Bearer {values['TENANT_BETA_KEY']}\n", encoding="utf-8")
print("Private configuration ready: .env and .local/LOCAL-CREDENTIALS.txt (key values are not printed)")
