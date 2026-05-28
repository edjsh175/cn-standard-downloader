from __future__ import annotations

from typing import Any


API_VERSION = "2026-05-28"
TASK_TYPES = ["search_only", "direct_grab", "keyword_search"]
TERMINAL_STATES = ["succeeded", "failed", "partial_failed", "cancelled"]
ARTIFACT_NAMES = ["search_results", "failed_results", "log_file"]
RECOMMENDED_WORKFLOW = ["search_only", "direct_grab"]

ERROR_RETRYABLE = {
    "CAPTCHA_NO_BALANCE": True,
    "CAPTCHA_FAILED": True,
    "NO_PUBLIC_TEXT": False,
    "PDF_DOWNLOAD_FAILED": True,
    "DB_WRITE_FAILED": False,
    "SITE_TIMEOUT": True,
    "INVALID_INPUT": False,
    "UNKNOWN_ERROR": True,
}


def get_capabilities() -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "task_types": list(TASK_TYPES),
        "terminal_states": list(TERMINAL_STATES),
        "artifact_names": list(ARTIFACT_NAMES),
        "recommended_workflow": list(RECOMMENDED_WORKFLOW),
        "recommended_poll_interval_seconds": 2,
        "auth": {"scheme": "bearer"},
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def classify_error_code(message: Any, error_type: Any = None) -> str:
    reason = f"{_text(error_type)} {_text(message)}".lower()
    if not reason.strip():
        return "UNKNOWN_ERROR"

    if "\u65e0\u53ef\u7528\u9898\u5206" in reason or "no balance" in reason or "\u9898\u5206" in reason:
        return "CAPTCHA_NO_BALANCE"
    if "captcha" in reason or "\u9a8c\u8bc1\u7801" in reason:
        return "CAPTCHA_FAILED"
    if (
        "view text button not found" in reason
        or "standard not public" in reason
        or "not public" in reason
        or "copyright" in reason
        or "\u516c\u5f00" in reason
        or "\u7248\u6743" in reason
    ):
        return "NO_PUBLIC_TEXT"
    if "database" in reason or "db write" in reason or "standard_code missing" in reason or "\u5165\u5e93" in reason:
        return "DB_WRITE_FAILED"
    if "timeout" in reason or "timed out" in reason:
        return "SITE_TIMEOUT"
    if "download" in reason or "pdf" in reason or "\u4e0b\u8f7d" in reason:
        return "PDF_DOWNLOAD_FAILED"
    if "invalid" in reason or "required" in reason or "must " in reason:
        return "INVALID_INPUT"
    return "UNKNOWN_ERROR"


def _retryable(error_code: str | None) -> bool:
    if not error_code:
        return False
    return bool(ERROR_RETRYABLE.get(error_code, True))


def annotate_errors(errors: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    annotated = []
    for error in errors or []:
        row = dict(error)
        error_code = classify_error_code(row.get("message"), row.get("error_type"))
        row["error_code"] = error_code
        row["retryable"] = _retryable(error_code)
        annotated.append(row)
    return annotated


def _summary(result_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result_payload, dict):
        return {}
    summary = result_payload.get("summary")
    return summary if isinstance(summary, dict) else {}


def _errors(result_payload: dict[str, Any] | None, error_message: str | None) -> list[dict[str, Any]]:
    if isinstance(result_payload, dict):
        errors = result_payload.get("errors")
        if isinstance(errors, list) and errors:
            return annotate_errors(errors)
    if error_message:
        return annotate_errors([{"message": error_message}])
    return []


def _first_error_code(errors: list[dict[str, Any]]) -> str | None:
    if not errors:
        return None
    return str(errors[0].get("error_code") or "UNKNOWN_ERROR")


def _next_actions_for_error(error_code: str | None) -> list[str]:
    if error_code == "CAPTCHA_NO_BALANCE":
        return ["inspect_errors", "fix_captcha_account"]
    if error_code == "CAPTCHA_FAILED":
        return ["inspect_errors", "retry_task"]
    if error_code == "NO_PUBLIC_TEXT":
        return ["inspect_errors", "select_different_items"]
    if error_code == "DB_WRITE_FAILED":
        return ["inspect_errors", "fix_database"]
    if error_code == "INVALID_INPUT":
        return ["inspect_errors", "fix_request_payload"]
    if error_code in {"PDF_DOWNLOAD_FAILED", "SITE_TIMEOUT"}:
        return ["inspect_errors", "retry_task"]
    return ["inspect_errors", "download_artifacts"]


def _failed_outcome(error_code: str | None, succeeded: int, status: str) -> str:
    if status == "partial_failed" and succeeded > 0:
        return "partial_downloaded"
    if error_code in {"CAPTCHA_NO_BALANCE", "CAPTCHA_FAILED"}:
        return "blocked_captcha"
    if error_code == "NO_PUBLIC_TEXT":
        return "not_public"
    return "failed"


def build_agent_status(
    task_type: str | None,
    status: str | None,
    result_payload: dict[str, Any] | None,
    error_message: str | None,
) -> dict[str, Any]:
    lifecycle = _text(status) or "unknown"
    terminal = lifecycle in TERMINAL_STATES

    if not terminal:
        return {
            "lifecycle": lifecycle,
            "terminal": False,
            "outcome": "pending",
            "retryable": False,
            "error_code": None,
            "next_actions": ["poll_task", "cancel_task"],
        }

    summary = _summary(result_payload)
    total = int(summary.get("total") or 0)
    succeeded = int(summary.get("succeeded") or 0)
    errors = _errors(result_payload, error_message)
    error_code = _first_error_code(errors)

    if lifecycle == "succeeded":
        if task_type == "search_only":
            if total > 0:
                return {
                    "lifecycle": lifecycle,
                    "terminal": True,
                    "outcome": "results_available",
                    "retryable": False,
                    "error_code": None,
                    "next_actions": ["fetch_result", "select_items_for_direct_grab", "download_artifacts"],
                }
            return {
                "lifecycle": lifecycle,
                "terminal": True,
                "outcome": "no_results",
                "retryable": False,
                "error_code": None,
                "next_actions": ["fetch_result", "inspect_errors"],
            }

        if total > 0 and succeeded == total:
            return {
                "lifecycle": lifecycle,
                "terminal": True,
                "outcome": "downloaded",
                "retryable": False,
                "error_code": None,
                "next_actions": ["fetch_result", "download_artifacts", "download_pdfs"],
            }

        return {
            "lifecycle": lifecycle,
            "terminal": True,
            "outcome": "no_results",
            "retryable": False,
            "error_code": None,
            "next_actions": ["fetch_result", "inspect_errors"],
        }

    outcome = _failed_outcome(error_code, succeeded, lifecycle)
    return {
        "lifecycle": lifecycle,
        "terminal": True,
        "outcome": outcome,
        "retryable": _retryable(error_code),
        "error_code": error_code,
        "next_actions": _next_actions_for_error(error_code),
    }
