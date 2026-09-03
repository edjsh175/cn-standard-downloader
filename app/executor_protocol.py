"""Dependency boundaries for the real and fake crawler executors."""

from __future__ import annotations

from typing import Any, Callable, Protocol


class SearchExecutor(Protocol):
    def __call__(
        self,
        keywords: list[str],
        *,
        output_filename: str,
        log_file: str,
        cancel_checker: Callable[[], bool],
        per_keyword_limit: int | None,
    ) -> dict[str, Any]: ...


class CrawlerFactory(Protocol):
    def __call__(
        self,
        *,
        log_file: str,
        cancel_checker: Callable[[], bool],
        duplicate_policy: str,
    ) -> Any: ...


class ExcelWriter(Protocol):
    def __call__(self, records: list[dict[str, Any]], output_filename: str) -> None: ...
