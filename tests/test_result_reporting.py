"""Regression tests for Colab bridge result reporting (no live database required)."""
import unittest
from fastapi import HTTPException

import main


class ResultReportingTests(unittest.TestCase):
    def setUp(self):
        self.old_token = main.BRIDGE_TOKEN
        self.old_database_url = main.DATABASE_URL
        main.BRIDGE_TOKEN = "unit-test-token"
        main.DATABASE_URL = ""
        with main._lock:
            main._results.clear()
            main._known_task_ids.clear()

    def tearDown(self):
        main.BRIDGE_TOKEN = self.old_token
        main.DATABASE_URL = self.old_database_url
        with main._lock:
            main._results.clear()
            main._known_task_ids.clear()

    def test_result_post_returns_task_id_and_storage_mode(self):
        main._known_task_ids.append("test-task-123")
        body = main.ResultBody(
            task_id="test-task-123",
            status="completed",
            output="Hello from Colab!\n4",
        )
        response = main.post_result(body, "Bearer unit-test-token")
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["task_id"], "test-task-123")
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["storage"], "memory")

    def test_result_can_be_retrieved_by_same_task_id(self):
        main._known_task_ids.append("test-task-456")
        body = main.ResultBody(
            task_id="test-task-456",
            status="completed",
            output="Hello from Colab!\n4",
        )
        main.post_result(body, "Bearer unit-test-token")
        result = main.get_task_result("test-task-456")
        self.assertIn("Status: completed", result)
        self.assertIn("Hello from Colab!\n4", result)

    def test_invalid_token_is_rejected(self):
        main._known_task_ids.append("test-task-789")
        body = main.ResultBody(
            task_id="test-task-789",
            status="completed",
            output="not secret",
        )
        with self.assertRaises(HTTPException) as caught:
            main.post_result(body, "Bearer wrong-token")
        self.assertEqual(caught.exception.status_code, 401)

    def test_unknown_task_id_is_rejected_in_memory_mode(self):
        body = main.ResultBody(
            task_id="never-queued-task",
            status="completed",
            output="must not be stored",
        )
        with self.assertRaises(HTTPException) as caught:
            main.post_result(body, "Bearer unit-test-token")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn("never-queued-task", main._results)

    def test_result_status_validation_rejects_unknown_status(self):
        with self.assertRaises(Exception):
            main.ResultBody(
                task_id="test-task-invalid",
                status="unknown",
                output="",
            )


if __name__ == "__main__":
    unittest.main()
