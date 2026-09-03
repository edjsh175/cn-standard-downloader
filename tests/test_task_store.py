import unittest
from unittest.mock import patch

from app.task_store import TaskStore


class FakeCursor:
    def __init__(self, fetchone_result=None, fetchall_result=None, rowcount=1):
        self.fetchone_result = fetchone_result
        self.fetchall_result = fetchall_result or []
        self.rowcount = rowcount
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result

    def close(self):
        return None


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def close(self):
        return None


class TaskStoreLifecycleTests(unittest.TestCase):
    def make_store(self, cursor):
        store = TaskStore.__new__(TaskStore)
        return store, FakeConnection(cursor)

    def test_claim_task_uses_lease_and_increments_attempt(self):
        cursor = FakeCursor(rowcount=1)
        store, connection = self.make_store(cursor)

        with patch.object(store, "_connect", return_value=connection):
            claimed = store.claim_task("task-1", "worker-a", lease_seconds=90)

        self.assertTrue(claimed)
        sql, params = cursor.calls[-1]
        self.assertIn("lease_owner", sql)
        self.assertIn("lease_until", sql)
        self.assertIn("attempt_count=attempt_count+1", sql)
        self.assertEqual(params, ("worker-a", 90, "task-1"))

    def test_recover_expired_tasks_requeues_running_work(self):
        cursor = FakeCursor(rowcount=2)
        store, connection = self.make_store(cursor)

        with patch.object(store, "_connect", return_value=connection):
            recovered = store.recover_expired_tasks()

        self.assertEqual(recovered, 2)
        sql, params = cursor.calls[-1]
        self.assertIn("status='pending'", sql)
        self.assertIn("lease_until", sql)
        self.assertIsNone(params)

    def test_list_runnable_tasks_returns_pending_and_queued_ids_by_priority(self):
        cursor = FakeCursor(fetchall_result=[{"id": "task-2"}, {"id": "task-1"}])
        store, connection = self.make_store(cursor)

        with patch.object(store, "_connect", return_value=connection):
            task_ids = store.list_runnable_task_ids()

        self.assertEqual(task_ids, ["task-2", "task-1"])
        sql, params = cursor.calls[-1]
        self.assertIn("status IN ('pending', 'queued')", sql)
        self.assertIn("priority DESC", sql)
        self.assertIsNone(params)

    def test_create_task_checks_idempotency_key_before_insert(self):
        cursor = FakeCursor(fetchone_result=("existing-task",))
        store, connection = self.make_store(cursor)

        with patch.object(store, "_connect", return_value=connection):
            task_id = store.create_task(
                "search_only",
                {"keywords": ["AI"], "idempotency_key": "request-123"},
            )

        self.assertEqual(task_id, "existing-task")
        self.assertEqual(len(cursor.calls), 1)
        self.assertIn("idempotency_key", cursor.calls[0][0])


if __name__ == "__main__":
    unittest.main()
