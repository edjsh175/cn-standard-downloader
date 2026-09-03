"""Machine-readable contract for the crawler's Agent-facing tools.

This module describes the execution engine, not an LLM Agent.  The contract is
kept in Python for now so the worker and its tests share one source of truth.
It is intentionally JSON-serializable and can later be exported as OpenAPI or
JSON Schema without changing the public shape.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.task_state import TERMINAL_STATE_ORDER


CONTRACT_VERSION = "1.0.0"
MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024
MAX_DIRECT_ITEMS = 500
MAX_KEYWORDS = 50

ERROR_CATALOG = {
    "CAPTCHA_NO_BALANCE": {
        "category": "external_dependency",
        "retryable": True,
        "human_intervention": True,
    },
    "CAPTCHA_FAILED": {
        "category": "external_dependency",
        "retryable": True,
        "human_intervention": True,
    },
    "NO_PUBLIC_TEXT": {
        "category": "source_policy",
        "retryable": False,
        "human_intervention": False,
    },
    "PDF_DOWNLOAD_FAILED": {
        "category": "download",
        "retryable": True,
        "human_intervention": False,
    },
    "DB_WRITE_FAILED": {
        "category": "persistence",
        "retryable": False,
        "human_intervention": False,
    },
    "SITE_TIMEOUT": {
        "category": "upstream",
        "retryable": True,
        "human_intervention": False,
    },
    "INVALID_INPUT": {
        "category": "request",
        "retryable": False,
        "human_intervention": False,
    },
    "UNKNOWN_ERROR": {
        "category": "internal",
        "retryable": True,
        "human_intervention": False,
    },
    "INTERNAL_ERROR": {
        "category": "internal",
        "retryable": False,
        "human_intervention": False,
    },
    "REQUEST_BODY_TOO_LARGE": {
        "category": "request",
        "retryable": False,
        "human_intervention": False,
    },
}

_TOOLS = [
    {
        "name": "search_standards",
        "description": "Search candidate national standards and return structured items.",
        "operation": "POST /api/tasks",
        "task_type": "search_only",
        "input_schema": {
            "type": "object",
            "required": ["keywords"],
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_KEYWORDS},
                "per_keyword_limit": {"type": ["integer", "null"], "minimum": 1},
                "idempotency_key": {"type": "string", "maxLength": 128},
            },
        },
        "next_actions": ["get_task_status", "get_task_result"],
    },
    {
        "name": "download_standards",
        "description": "Download selected standard documents and persist item results.",
        "operation": "POST /api/tasks",
        "task_type": "direct_grab",
        "input_schema": {
            "type": "object",
            "required": ["items"],
            "properties": {
                "table_name": {"type": "string"},
                "items": {"type": "array", "minItems": 1, "maxItems": MAX_DIRECT_ITEMS},
                "detail_urls": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_DIRECT_ITEMS},
                "duplicate_policy": {"type": "string", "enum": ["overwrite", "skip"]},
                "idempotency_key": {"type": "string", "maxLength": 128},
            },
        },
        "next_actions": ["get_task_status", "get_task_result", "get_artifact"],
    },
    {
        "name": "get_task_status",
        "description": "Read lifecycle and machine-readable outcome for a task.",
        "operation": "GET /api/tasks/{task_id}",
        "input_schema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}},
        "next_actions": ["get_task_status", "get_task_result", "cancel_task"],
    },
    {
        "name": "get_task_result",
        "description": "Read structured item results, errors, and artifact references.",
        "operation": "GET /api/tasks/{task_id}/result",
        "input_schema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}},
        "next_actions": ["download_standards", "get_artifact"],
    },
    {
        "name": "cancel_task",
        "description": "Request best-effort cancellation of a non-terminal task.",
        "operation": "POST /api/tasks/{task_id}/cancel",
        "input_schema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}},
        "next_actions": ["get_task_status", "get_task_result"],
    },
    {
        "name": "get_artifact",
        "description": "Download a task artifact such as search results or failed items.",
        "operation": "GET /api/tasks/{task_id}/artifacts/{artifact_name}",
        "input_schema": {
            "type": "object",
            "required": ["task_id", "artifact_name"],
            "properties": {
                "task_id": {"type": "string"},
                "artifact_name": {"type": "string", "enum": ["search_results", "failed_results", "log_file"]},
            },
        },
        "next_actions": [],
    },
]


def get_tool_contract() -> dict[str, Any]:
    """Return an independent, JSON-serializable copy of the public contract."""

    return {
        "contract_version": CONTRACT_VERSION,
        "api_version": "2026-05-28",
        "tools": deepcopy(_TOOLS),
        "limits": {
            "max_request_body_bytes": MAX_REQUEST_BODY_BYTES,
            "max_direct_items": MAX_DIRECT_ITEMS,
            "max_keywords": MAX_KEYWORDS,
            "recommended_poll_interval_seconds": 2,
        },
        "terminal_states": list(TERMINAL_STATE_ORDER),
        "artifact_schema": {
            "required": ["name", "content_type", "size_bytes", "sha256"],
        },
        "error_catalog": deepcopy(ERROR_CATALOG),
        "auth": {"scheme": "bearer"},
    }
