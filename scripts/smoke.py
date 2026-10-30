import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

BASE = os.environ.get("INGESTFLOW_BASE_URL", "http://127.0.0.1:8100")
address = urlsplit(BASE)
if address.scheme != "http" or address.username is not None or address.password is not None or address.path not in ("", "/") or address.query or address.fragment or not (
    address.hostname == "127.0.0.1" and address.port is not None or address.hostname == "api" and address.port == 8100
):
    raise SystemExit("Smoke probe accepts only local or Compose API addresses")
BASE = BASE.rstrip("/")
alpha = os.environ["TENANT_ALPHA_KEY"]
beta = os.environ["TENANT_BETA_KEY"]


def request(method, path, token=None, body=None, extra=None):
    headers = dict(extra or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, dict(response.headers), json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), json.load(error)


assert request("GET", "/health")[0] == 200
assert request("GET", "/v1/imports")[0] == 401
payload = b"sku,name,quantity\nSMOKE-001,Synthetic smoke record,7\n"
key = "smoke-" + uuid4().hex
headers = {"Content-Type": "text/csv", "Idempotency-Key": key}
code, response_headers, job = request("POST", "/v1/imports", alpha, payload, headers)
assert code == 202
path = f"/v1/imports/{job['id']}"
assert response_headers.get("Location", response_headers.get("location")) == path
assert request("GET", path, beta)[0] == 404
replay = request("POST", "/v1/imports", alpha, payload, headers)
assert replay[0] == 202 and replay[2]["id"] == job["id"]
assert request("POST", "/v1/imports", alpha, payload + b"\n", headers)[0] == 409
deadline = time.monotonic() + 40
while time.monotonic() < deadline:
    final = request("GET", path, alpha)[2]
    if final["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
        break
    time.sleep(0.2)
assert final["status"] == "SUCCEEDED" and final["applied_count"] == 1
records = request("GET", "/v1/records?after=SMOKE-000", alpha)[2]["items"]
assert any(row["sku"] == "SMOKE-001" and row["quantity"] == 7 for row in records)
assert request("POST", path + "/cancel", alpha)[0] == 409
print(json.dumps({"probe": "actual-http-worker", "status": "passed", "accepted": 202, "replayed_same_id": True, "conflict": 409, "cross_tenant": 404, "worker_status": final["status"], "applied_count": 1}))
