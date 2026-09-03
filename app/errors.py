"""Typed errors shared by crawler stages and the Agent-facing contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.tool_contract import ERROR_CATALOG


class ErrorCode(str, Enum):
    CAPTCHA_NO_BALANCE = "CAPTCHA_NO_BALANCE"
    CAPTCHA_FAILED = "CAPTCHA_FAILED"
    NO_PUBLIC_TEXT = "NO_PUBLIC_TEXT"
    PDF_DOWNLOAD_FAILED = "PDF_DOWNLOAD_FAILED"
    DB_WRITE_FAILED = "DB_WRITE_FAILED"
    SITE_TIMEOUT = "SITE_TIMEOUT"
    INVALID_INPUT = "INVALID_INPUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    REQUEST_BODY_TOO_LARGE = "REQUEST_BODY_TOO_LARGE"


@dataclass(frozen=True)
class WorkerError(Exception):
    code: ErrorCode | str
    message: str
    detail_url: str | None = None
    error_type: str | None = None

    def __post_init__(self):
        Exception.__init__(self, self.message)

    @property
    def normalized_code(self) -> str:
        code = self.code.value if isinstance(self.code, ErrorCode) else str(self.code)
        return code if code in ERROR_CATALOG else ErrorCode.UNKNOWN_ERROR.value

    def to_dict(self) -> dict[str, Any]:
        code = self.normalized_code
        spec = ERROR_CATALOG[code]
        result: dict[str, Any] = {}
        if self.detail_url:
            result["detail_url"] = self.detail_url
        result.update(
            {
                "error_code": code,
                "retryable": bool(spec["retryable"]),
                "category": spec["category"],
                "message": self.message,
            }
        )
        if self.error_type:
            result["error_type"] = self.error_type
        return result
