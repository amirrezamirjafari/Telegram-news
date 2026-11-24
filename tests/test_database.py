import tempfile
import unittest
from pathlib import Path

import database


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        fd = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        fd.close()
        database.DB_PATH = Path(fd.name)
        database.init_db()

    def tearDown(self):
        database.DB_PATH.unlink(missing_ok=True)

    def test_post_is_deduplicated(self):
        first = database.save_post(
            "forexnews", 10, "test", "2026-01-01T00:00:00+00:00",
            "https://t.me/forexnews/10",
        )
        second = database.save_post(
            "forexnews", 10, "test", "2026-01-01T00:00:00+00:00",
            "https://t.me/forexnews/10",
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(database.latest_posts("forexnews")), 1)

    def test_subscriber_subscription(self):
        database.add_subscriber(123)
        self.assertIn(123, database.active_subscribers())
        database.remove_subscriber(123)
        self.assertNotIn(123, database.active_subscribers())

    def test_analysis_retries_are_scheduled_and_capped(self):
        database.save_post(
            "forexnews", 20, "Bank rates change",
            "2026-01-01T00:00:00+00:00", "",
        )

        for expected_attempt in range(1, 6):
            attempt = database.begin_analysis_attempt(
                "forexnews", 20, max_attempts=5
            )
            self.assertEqual(attempt, expected_attempt)
            retry_delay = 0 if expected_attempt < 5 else None
            database.save_analysis_error(
                "forexnews", 20, "temporary failure",
                retry_after_seconds=retry_delay,
            )

        self.assertEqual(database.retryable_posts(max_attempts=5), [])
        self.assertIsNone(
            database.begin_analysis_attempt("forexnews", 20, max_attempts=5)
        )

    def test_interrupted_analysis_is_requeued_after_recovery(self):
        database.save_post(
            "forexnews", 21, "Bank rates change",
            "2026-01-01T00:00:00+00:00", "",
        )
        database.begin_analysis_attempt("forexnews", 21, max_attempts=5)

        database.recover_interrupted_analyses(max_attempts=5)

        self.assertEqual(
            [(post[0], post[1]) for post in database.retryable_posts(5)],
            [("forexnews", 21)],
        )


if __name__ == "__main__":
    unittest.main()
