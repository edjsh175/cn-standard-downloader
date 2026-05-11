import sys

from app.pipeline import PipelineRunner
from app.task_store import TaskStore


def _result_error_message(result: dict) -> str | None:
    summary = result.get("summary") or {}
    failed_count = int(summary.get("failed") or 0)
    if failed_count <= 0:
        return None
    errors = result.get("errors") or []
    if errors:
        message = str(errors[0].get("message") or "").strip()
        if message:
            return message
    return f"{failed_count} item(s) failed"


def run_task(task_id: str) -> int:
    task_store = TaskStore()
    pipeline = PipelineRunner(task_store)

    try:
        if task_store.is_cancel_requested(task_id):
            task_store.mark_cancelled(task_id)
            return 0

        result = pipeline.execute(task_id)
        if task_store.is_cancel_requested(task_id):
            task_store.mark_cancelled(task_id, result_payload=result)
        elif result.get("status") == "succeeded":
            task_store.mark_succeeded(task_id, result)
        else:
            task_store.mark_completed(
                task_id,
                result.get("status", "failed"),
                result,
                error_message=_result_error_message(result),
            )
        return 0
    except RuntimeError as exc:
        if str(exc) == "Task cancelled":
            partial = {
                "task_id": task_id,
                "status": "cancelled",
                "result": task_store.get_task(task_id),
                "items": task_store.list_task_items(task_id),
                "error_message": None,
            }
            task_store.mark_cancelled(task_id, result_payload=partial)
            return 0
        task_store.mark_failed(task_id, str(exc))
        return 1
    except Exception as exc:
        task_store.mark_failed(task_id, str(exc))
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.task_runner <task_id>")
    raise SystemExit(run_task(sys.argv[1]))
