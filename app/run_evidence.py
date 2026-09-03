"""Small, JSON-serializable execution evidence for Agent-visible task results."""

from __future__ import annotations

import time
from typing import Any


class RunEvidence:
    def __init__(self):
        self.started_at = time.perf_counter()
        self.phases: dict[str, dict[str, Any]] = {}

    def begin(self) -> float:
        return time.perf_counter()

    def finish(self, name: str, started_at: float, **counts: int):
        self.phases[name] = {
            "duration_ms": round(max(0.0, time.perf_counter() - started_at) * 1000, 3),
            **counts,
        }

    def attach(self, result: dict[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        payload["run_evidence"] = {
            "duration_ms": round(max(0.0, time.perf_counter() - self.started_at) * 1000, 3),
            "phases": dict(self.phases),
        }
        return payload
