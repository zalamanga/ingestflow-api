from pathlib import Path
import hashlib
import json

from ingestflow.api import create_app
from ingestflow.config import Settings

settings = Settings("postgresql://unused/unused", hashlib.sha256(b"a" * 64).hexdigest(), hashlib.sha256(b"b" * 64).hexdigest())
target = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
target.write_text(json.dumps(create_app(settings).openapi(), indent=2) + "\n", encoding="utf-8")
print("Generated docs/openapi.json from the actual FastAPI route definitions")
