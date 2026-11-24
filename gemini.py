import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config


class GeminiAPIError(RuntimeError):
    """A safe-to-log Gemini failure that never includes credentials."""


def analyze_news(text, channel=""):
    if not config.GEMINI_API_KEY:
        raise GeminiAPIError(
            "GEMINI_API_KEY is not configured; add it to the local .env file"
        )

    prompt = (
        "Analyze this Telegram news post for financial markets. Respond only "
        "with a JSON object containing: impact_level (high, medium, or low), "
        "impact_score (integer 0-100), sentiment (bullish, bearish, neutral, "
        "or mixed), affected_assets (array of strings), "
        "fundamental_analysis (string), sentiment_analysis (string), "
        "chart_impact (string), confidence (integer 0-100), and rationale "
        "(string). Assess likely direction and time horizon cautiously; "
        "explain uncertainty and do not present predictions as guarantees or "
        "personalized investment advice. Write analysis in Persian. "
        f"Source channel: @{channel}\nNews:\n{text}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent"
    )
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": config.GEMINI_API_KEY,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise GeminiAPIError(
            f"Gemini API returned HTTP {exc.code}"
        ) from None
    except (URLError, TimeoutError):
        raise GeminiAPIError(
            "Gemini API request failed; check network connectivity"
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GeminiAPIError("Gemini API returned an invalid response") from None

    try:
        response_text = payload["candidates"][0]["content"]["parts"][0]["text"]
        analysis = json.loads(response_text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise GeminiAPIError(
            "Gemini API response did not contain valid analysis JSON"
        ) from None

    return _validate_analysis(analysis)


def _validate_analysis(data):
    levels = {"high", "medium", "low"}
    sentiments = {"bullish", "bearish", "neutral", "mixed"}
    required_strings = (
        "fundamental_analysis",
        "sentiment_analysis",
        "chart_impact",
        "rationale",
    )
    if not isinstance(data, dict):
        raise GeminiAPIError("Gemini analysis has an invalid structure")
    if data.get("impact_level") not in levels:
        raise GeminiAPIError("Gemini analysis has an invalid impact level")
    if data.get("sentiment") not in sentiments:
        raise GeminiAPIError("Gemini analysis has an invalid sentiment")
    for key in ("impact_score", "confidence"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise GeminiAPIError(f"Gemini analysis has an invalid {key}")
    if not isinstance(data.get("affected_assets"), list) or not all(
        isinstance(item, str) for item in data["affected_assets"]
    ):
        raise GeminiAPIError("Gemini analysis has invalid affected assets")
    for key in required_strings:
        if not isinstance(data.get(key), str):
            raise GeminiAPIError(f"Gemini analysis is missing {key}")
    return data
