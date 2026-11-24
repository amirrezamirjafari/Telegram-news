import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config


class ModelAPIError(RuntimeError):
    """A safe-to-log model API failure that never includes credentials."""


def analyze_news(text, channel=""):
    if not config.MODEL_API_KEY:
        raise ModelAPIError(
            "MODEL_API_KEY is not configured; add it to the local .env file"
        )

    prompt = (
        "Analyze this Telegram news post for financial markets. Respond only "
        "with a valid JSON object containing: impact_level (high, medium, or "
        "low), impact_score (integer 0-100), sentiment (bullish, bearish, "
        "neutral, or mixed), affected_assets (array of strings), "
        "fundamental_analysis (string), sentiment_analysis (string), "
        "chart_impact (string), confidence (integer 0-100), and rationale "
        "(string). Assess likely direction and time horizon cautiously; "
        "explain uncertainty and do not present predictions as guarantees or "
        "personalized investment advice. Write analysis in Persian. "
        f"Source channel: @{channel}\nNews:\n{text}"
    )
    body = json.dumps(
        {
            "model": config.MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only the requested JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = Request(
        f"{config.MODEL_API_BASE_URL.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.MODEL_API_KEY}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ModelAPIError(
            f"Model API returned HTTP {exc.code}"
        ) from None
    except (URLError, TimeoutError):
        raise ModelAPIError(
            "Model API request failed; check network connectivity"
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelAPIError("Model API returned an invalid response") from None

    try:
        response_text = payload["choices"][0]["message"]["content"]
        analysis = json.loads(response_text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ModelAPIError(
            "Model API response did not contain valid analysis JSON"
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
        raise ModelAPIError("Model analysis has an invalid structure")
    if data.get("impact_level") not in levels:
        raise ModelAPIError("Model analysis has an invalid impact level")
    if data.get("sentiment") not in sentiments:
        raise ModelAPIError("Model analysis has an invalid sentiment")
    for key in ("impact_score", "confidence"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ModelAPIError(f"Model analysis has an invalid {key}")
    if not isinstance(data.get("affected_assets"), list) or not all(
        isinstance(item, str) for item in data["affected_assets"]
    ):
        raise ModelAPIError("Model analysis has invalid affected assets")
    for key in required_strings:
        if not isinstance(data.get(key), str):
            raise ModelAPIError(f"Model analysis is missing {key}")
    return data
