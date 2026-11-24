import io
import json
import unittest
from unittest.mock import patch

import config
from model_api import ModelAPIError, analyze_news


ANALYSIS = {
    "impact_level": "medium",
    "impact_score": 55,
    "sentiment": "neutral",
    "affected_assets": ["EUR/USD"],
    "fundamental_analysis": "آثار احتمالی",
    "sentiment_analysis": "خنثی",
    "chart_impact": "نامشخص",
    "confidence": 60,
    "rationale": "اطلاعات محدود است",
}

MODEL_RESULT = {
    "is_advertisement": False,
    "advertisement_reason": "",
    "is_persian": False,
    "analysis": ANALYSIS,
}


class ModelAPITest(unittest.TestCase):
    def test_posts_to_configured_openai_compatible_endpoint(self):
        response = io.BytesIO(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    MODEL_RESULT, ensure_ascii=False
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )
        with patch.object(
            config, "MODEL_API_BASE_URL", "https://example.test/api/v1/"
        ), patch.object(
            config, "MODEL_API_KEY", "test-token"
        ), patch.object(
            config, "MODEL_NAME", "manageit/qwen3.8-27b"
        ), patch(
            "model_api.urlopen", return_value=response
        ) as urlopen:
            result = analyze_news("Bank rates change", "markets")

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            request.full_url,
            "https://example.test/api/v1/chat/completions",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(body["model"], "manageit/qwen3.8-27b")
        self.assertEqual(result, MODEL_RESULT)

    def test_requires_api_key(self):
        with patch.object(config, "MODEL_API_KEY", ""):
            with self.assertRaisesRegex(ModelAPIError, "MODEL_API_KEY"):
                analyze_news("Bank rates change")


if __name__ == "__main__":
    unittest.main()
