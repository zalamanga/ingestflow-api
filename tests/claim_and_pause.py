"""Internal crash-probe process; deliberately absent from the production image."""
from pathlib import Path
import sys
import threading

from ingestflow.config import Settings
from ingestflow.worker import claim

job = claim(Settings.from_env())
if job is None:
    raise SystemExit("Expected one queued import")
Path(sys.argv[1]).write_text(str(job["id"]), encoding="ascii")
threading.Event().wait(60)
raise SystemExit("Crash probe was not killed")
