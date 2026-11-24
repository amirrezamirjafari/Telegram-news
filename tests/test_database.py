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


if __name__ == "__main__":
    unittest.main()
