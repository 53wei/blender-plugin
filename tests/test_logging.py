"""Structured logging safety tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bsa.infra.logging import JsonlLogger


class LoggingTests(unittest.TestCase):
    def test_secret_fields_are_redacted(self) -> None:
        path = Path("benchmarks/results/test_events.jsonl")
        path.unlink(missing_ok=True)
        self.addCleanup(path.unlink, missing_ok=True)
        JsonlLogger(path, "session-1").emit(
            "scene.snapshot.created",
            api_key="do-not-write",
            object_count=3,
            headers={"Authorization": "Bearer nested-secret"},
            events=({"token": "tuple-secret"},),
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["api_key"], "[REDACTED]")
        serialized = path.read_text(encoding="utf-8")
        self.assertNotIn("do-not-write", serialized)
        self.assertNotIn("nested-secret", serialized)
        self.assertNotIn("tuple-secret", serialized)


if __name__ == "__main__":
    unittest.main()
