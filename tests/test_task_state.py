import unittest

from app.task_state import TERMINAL_STATES, TaskStateError, assert_transition, is_terminal


class TaskStateTests(unittest.TestCase):
    def test_allows_queued_running_and_terminal_progression(self):
        assert_transition("pending", "queued")
        assert_transition("queued", "running")
        assert_transition("running", "partial_failed")
        self.assertTrue(is_terminal("partial_failed"))
        self.assertIn("cancelled", TERMINAL_STATES)

    def test_rejects_reopening_terminal_task(self):
        with self.assertRaises(TaskStateError):
            assert_transition("succeeded", "running")

    def test_rejects_unknown_states(self):
        with self.assertRaises(TaskStateError):
            assert_transition("pending", "not-a-state")


if __name__ == "__main__":
    unittest.main()
