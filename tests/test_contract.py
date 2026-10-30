import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from ingestflow.api import create_app
from ingestflow.config import Settings


def app():
    return create_app(Settings("postgresql://unused:unused@127.0.0.1:1/unused", hashlib.sha256(b"a" * 64).hexdigest(), hashlib.sha256(b"b" * 64).hexdigest()))


def test_openapi_describes_csv_bearer_and_idempotency():
    schema = app().openapi()
    submit = schema["paths"]["/v1/imports"]["post"]
    assert "text/csv" in submit["requestBody"]["content"]
    assert submit["security"] == [{"TenantBearer": []}]
    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in submit["parameters"])
    assert "202" in submit["responses"]
    assert "security" not in schema["paths"]["/health"]["get"]


def test_unauthorized_and_body_bounds_do_not_need_database():
    with TestClient(app()) as client:
        assert client.get("/v1/imports").status_code == 401
        assert client.get("/v1/imports", headers={"Authorization": "Bearer " + "c" * 64}).status_code == 401
        headers = {"Authorization": "Bearer " + "a" * 64, "Content-Type": "text/csv", "Idempotency-Key": "bounded"}
        oversized = client.post("/v1/imports", headers=headers, content=b"x" * 262145)
        assert oversized.status_code == 413 and oversized.json()["error"]["code"] == "payload_too_large"
        assert client.post("/v1/imports", headers={**headers, "Content-Type": "application/json"}, content=b"{}").status_code == 415
        assert client.post("/v1/imports", headers=headers, content=b"").status_code == 400


def test_database_unavailable_response_redacts_connection_details():
    with TestClient(app()) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.headers["retry-after"] == "1"
        assert response.json()["error"]["code"] == "database_unavailable"
        assert "unused" not in response.text and "postgresql://" not in response.text


def test_checked_in_openapi_matches_actual_routes():
    snapshot = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    assert json.loads(snapshot.read_text(encoding="utf-8")) == app().openapi()
