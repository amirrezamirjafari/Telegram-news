import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from model_api import ModelAPIError
from news_filter import fingerprint, is_financially_relevant, normalize_news
from processor import process_post


ANALYSIS = {
    "impact_level": "high",
    "impact_score": 83,
    "sentiment": "mixed",
    "affected_assets": ["EUR/USD"],
    "fundamental_analysis": "آثار احتمالی بر نرخ‌ها",
    "sentiment_analysis": "واکنش بازار ترکیبی است",
    "chart_impact": "نوسان کوتاه‌مدت محتمل است",
    "confidence": 72,
    "rationale": "نتیجه به داده‌های بعدی بستگی دارد",
}


def model_result(analysis=ANALYSIS, is_advertisement=False, is_persian=False):
    return {
        "is_advertisement": is_advertisement,
        "advertisement_reason": "تبلیغ خدمات کانال" if is_advertisement else "",
        "is_persian": is_persian,
        "analysis": None if is_advertisement or is_persian else analysis,
    }


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs["text"])


class NewsProcessingTest(unittest.TestCase):
    def setUp(self):
        fd = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        fd.close()
        self.db_path = Path(fd.name)
        database.DB_PATH = self.db_path
        database.init_db()
        database.add_subscriber(123)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_financial_filter_handles_english_and_persian(self):
        self.assertTrue(
            is_financially_relevant(
                "The Federal Reserve signals a possible interest rate cut."
            )
        )
        self.assertTrue(is_financially_relevant("بانک مرکزی نرخ بهره را تغییر داد"))
        self.assertFalse(is_financially_relevant("A new film opens this weekend"))

    def test_normalization_and_fingerprint_ignore_formatting(self):
        first = "Fed raises rates! https://example.com/news"
        second = "FED raises rates"
        self.assertEqual(normalize_news(first), normalize_news(second))
        self.assertEqual(fingerprint(first), fingerprint(second))

    def test_sends_raw_before_analysis_and_persists_analysis(self):
        bot = FakeBot()
        with patch("processor.analyze_news", return_value=model_result()):
            result = asyncio.run(
                process_post(
                    "markets", 10,
                    "The Federal Reserve signals a possible interest rate cut.",
                    "2026-11-24T12:00:00+00:00",
                    "https://t.me/markets/10",
                    bot,
                    notify=True,
                )
            )
        self.assertEqual(result, "processed")
        self.assertIn("منبع", bot.messages[0])
        self.assertIn("تحلیل Qwen", bot.messages[1])
        self.assertIn("⚡", bot.messages[1])
        self.assertIn("این تحلیل توصیه سرمایه گذاری نیست.", bot.messages[1])
        self.assertNotIn("این تحلیل احتمالی", bot.messages[1])
        news = database.latest_news(limit=1)[0]
        self.assertEqual(news[6], "complete")
        self.assertEqual(json.loads(news[5]), ANALYSIS)

    def test_filters_irrelevant_and_deduplicates_near_identical_news(self):
        bot = FakeBot()
        with patch("processor.analyze_news", return_value=model_result()) as analyze:
            irrelevant = asyncio.run(
                process_post(
                    "markets", 1, "A new film opens this weekend",
                    "2026-11-24T12:00:00+00:00", "", bot, notify=True,
                )
            )
            original_text = (
                "The Federal Reserve announced a surprise interest rate cut "
                "after inflation slowed, sending stock markets higher today."
            )
            original = asyncio.run(
                process_post(
                    "markets", 2, original_text,
                    "2026-11-24T12:01:00+00:00", "", bot, notify=True,
                )
            )
            repeat = asyncio.run(
                process_post(
                    "wire", 3,
                    "The Federal Reserve announced an unexpected interest "
                    "rate reduction after inflation slowed, sending stock "
                    "markets higher today! https://example.com/story",
                    "2026-11-24T12:02:00+00:00", "", bot, notify=True,
                )
            )
        self.assertEqual(
            (irrelevant, original, repeat),
            ("filtered", "processed", "duplicate"),
        )
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(len(bot.messages), 2)
        with database.connect() as connection:
            row = connection.execute(
                """
                SELECT relevant, duplicate_of_channel,
                       duplicate_of_message_id, dedup_method, analysis_status
                FROM posts WHERE channel='wire' AND message_id=3
                """
            ).fetchone()
            filtered_status = connection.execute(
                "SELECT analysis_status FROM posts WHERE channel='markets' AND message_id=1"
            ).fetchone()[0]
        self.assertEqual(row, (1, "markets", 2, "near", "duplicate"))
        self.assertEqual(filtered_status, "filtered")

    def test_latest_news_prioritizes_higher_impact_analysis(self):
        bot = FakeBot()
        lower = {**ANALYSIS, "impact_level": "low", "impact_score": 20}
        higher = {**ANALYSIS, "impact_level": "high", "impact_score": 90}
        with patch(
            "processor.analyze_news",
            side_effect=[model_result(lower), model_result(higher)],
        ):
            asyncio.run(
                process_post(
                    "markets", 20, "Bank shares rise as rates fall.",
                    "2026-11-24T12:02:00+00:00", "", bot, notify=False,
                )
            )
            asyncio.run(
                process_post(
                    "markets", 21, "Central bank unexpectedly cuts rates.",
                    "2026-11-24T12:01:00+00:00", "", bot, notify=False,
                )
            )
        self.assertEqual(database.latest_news(limit=2)[0][1], 21)

    def test_existing_unprocessed_posts_are_classified_without_backlog_delivery(self):
        bot = FakeBot()
        text = "Central bank signals a possible interest rate increase."
        database.save_post(
            "markets", 30, text, "2026-11-24T11:00:00+00:00", ""
        )
        with patch("processor.analyze_news", return_value=model_result()):
            result = asyncio.run(
                process_post(
                    "markets", 30, text, "2026-11-24T11:00:00+00:00",
                    "", bot, notify=True,
                )
            )
        self.assertEqual(result, "processed")
        self.assertEqual(bot.messages, [])
        self.assertEqual(database.latest_news(limit=1)[0][6], "complete")

    def test_persian_news_is_sent_without_analysis(self):
        bot = FakeBot()
        with patch(
            "processor.analyze_news",
            return_value=model_result(is_persian=True),
        ) as analyze:
            result = asyncio.run(
                process_post(
                    "markets", 31, "بانک مرکزی نرخ بهره را تغییر داد",
                    "2026-11-24T11:01:00+00:00", "https://t.me/markets/31",
                    bot, notify=True,
                )
            )

        self.assertEqual(result, "analysis_not_required")
        analyze.assert_called_once()
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("منبع", bot.messages[0])
        self.assertEqual(database.latest_news(limit=1)[0][5], None)
        self.assertEqual(database.latest_news(limit=1)[0][6], "not_required")

    def test_advertisement_is_filtered_before_delivery(self):
        bot = FakeBot()
        with patch(
            "processor.analyze_news",
            return_value=model_result(is_advertisement=True),
        ) as classify:
            result = asyncio.run(
                process_post(
                    "markets", 32, "Join our paid forex signals group today.",
                    "2026-11-24T11:02:00+00:00", "https://t.me/markets/32",
                    bot, notify=True,
                )
            )

        self.assertEqual(result, "advertisement")
        classify.assert_called_once()
        self.assertEqual(bot.messages, [])
        self.assertEqual(database.latest_news(limit=10), [])
        with database.connect() as connection:
            status = connection.execute(
                "SELECT analysis_status FROM posts WHERE channel='markets' AND message_id=32"
            ).fetchone()[0]
        self.assertEqual(status, "advertisement")

    def test_analysis_failure_is_persisted_after_raw_delivery(self):
        bot = FakeBot()
        with patch(
            "processor.analyze_news",
            side_effect=ModelAPIError("MODEL_API_KEY is not configured"),
        ):
            result = asyncio.run(
                process_post(
                    "markets", 12, "Bank shares rise as rates fall.",
                    "2026-11-24T12:00:00+00:00", "", bot, notify=True,
                )
            )
        self.assertEqual(result, "analysis_failed")
        self.assertIn("منبع", bot.messages[0])
        self.assertIn("تحلیل", bot.messages[1])
        news = database.latest_news(limit=1)[0]
        self.assertEqual(news[6], "failed")
        self.assertIn("MODEL_API_KEY", news[7])


if __name__ == "__main__":
    unittest.main()
