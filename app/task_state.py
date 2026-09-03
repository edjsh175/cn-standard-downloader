"""Explicit lifecycle rules for persisted crawler tasks."""

from __future__ import annotations


TASK_STATES = (
    "pending",
    "queued",
    "running",
    "succeeded",
    "failed",
    "partial_failed",
    "cancelled",
)
TERMINAL_STATE_ORDER = ("succeeded", "failed", "partial_failed", "cancelled")
TERMINAL_STATES = frozenset(TERMINAL_STATE_ORDER)

ALLOWED_TRANSITIONS = {
    "pending": frozenset({"queued", "running", "cancelled"}),
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "partial_failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "partial_failed": frozenset(),
    "cancelled": frozenset(),
}


class TaskStateError(ValueError):
    """Raised when a task lifecycle transition is not allowed."""


def is_terminal(state: str | None) -> bool:
    return state in TERMINAL_STATES


def assert_transition(current: str, target: str) -> None:
    if current not in ALLOWED_TRANSITIONS:
        raise TaskStateError(f"unknown current task state: {current}")
    if target not in ALLOWED_TRANSITIONS:
        raise TaskStateError(f"unknown target task state: {target}")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise TaskStateError(f"invalid task state transition: {current} -> {target}")
