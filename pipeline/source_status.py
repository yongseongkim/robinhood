"""Record source checks separately from publication time, retaining the last good snapshot."""
from datetime import datetime, timezone
import json

from common import RAW


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(data)
    temporary.replace(path)


def check_source(name, collect):
    path = RAW / "source-status" / (name + ".json")
    status = json.loads(path.read_text()) if path.exists() else {}
    try:
        collect()
    except Exception as exc:
        # Request exceptions may contain authenticated URLs. Expose only the type.
        status.update(state="partial", reason=type(exc).__name__)
        print(f"{name}: {type(exc).__name__} · 이전 자료 유지")
    else:
        status = {"state": "complete"}
    status["checkedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if status["state"] == "complete":
        status["lastSuccess"] = status["checkedAt"]
    atomic_bytes(path, json.dumps(status, ensure_ascii=False).encode())
