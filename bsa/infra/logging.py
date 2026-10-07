"""Local JSONL event logging with secret-field redaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SECRET_MARKERS = ("api_key", "apikey", "authorization", "token", "secret")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(marker in key.lower() for marker in _SECRET_MARKERS) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


class JsonlLogger:
    """Append stable structured events to a caller-selected local path."""

    def __init__(self, path: Path, session_id: str) -> None:
        self._path = path
        self._session_id = session_id

    def emit(self, event: str, *, level: str = "INFO", **fields: Any) -> None:
        """Write one redacted event line."""
        payload = _redact(
            {
                "ts": datetime.now(UTC).isoformat(),
                "level": level,
                "event": event,
                "session_id": self._session_id,
                **fields,
            }
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
