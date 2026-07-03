"""Password-safe persistent deployment audit records."""

import json
from datetime import datetime, timezone
from pathlib import Path


def record_deployment_event(installation_directory: str, event: str, **details) -> None:
    safe_details = {
        key: value for key, value in details.items()
        if "password" not in key.lower() and "secret" not in key.lower()
    }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "details": safe_details,
    }
    try:
        log_dir = Path(installation_directory) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "deployment-audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass
