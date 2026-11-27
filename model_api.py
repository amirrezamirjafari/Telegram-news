import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config


class ModelAPIError(RuntimeError):
    """A safe-to-log model API failure that never includes credentials."""

    def __init__(self, message, retryable=False, retry_after_seconds=None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def _retry_after_seconds(value):
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (retry_at - datetime.now(timezone.utc)).total_seconds(),
        )


def analyze_news(text, channel="", base_url=None, api_key=None, model=None):
    base_url = base_url or config.MODEL_API_BASE_URL
    api_key = api_key if api_key is not None else config.MODEL_API_KEY
    model = model or config.MODEL_NAME
    if not api_key:
        raise ModelAPIError(
            "MODEL_API_KEY is not configured; add it to the local .env file"
        )

    prompt = (
        "Classify this Telegram post and analyze it only when requested. "
        "Respond only with a valid JSON object containing is_advertisement "
        "(boolean), advertisement_reason (string), is_persian (boolean), and "
        "analysis (object or null). Set is_advertisement to true for channel "
        "self-promotion, invitations to join/follow, paid courses or signals, "
        "affiliate/referral promotions, and ads for the channel's own services. "
        "Do not classify ordinary reporting about a company's product as an ad. "
        "Set is_persian according to the post's primary language. If the post "
        "is an advertisement or is primarily in Persian, set analysis to null. "
        "Otherwise analysis must contain impact_level (high, medium, or low), "
        "impact_score (integer 0-100), sentiment (bullish, bearish, neutral, "
        "or mixed), affected_assets (array of strings), fundamental_analysis "
        "(string), sentiment_analysis (string), chart_impact (string), "
        "confidence (integer 0-100), and rationale (string). Assess likely "
        "direction and time horizon cautiously; explain uncertainty and do not "
        "present predictions as guarantees or personalized investment advice. "
        "Write advertisement_reason and analysis in Persian. "
        f"Source channel: @{channel}\nPost:\n{text}"
    )
    body = json.dumps(
        {
            "model": model,
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
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ModelAPIError(
            f"Model API returned HTTP {exc.code}",
            retryable=exc.code == 429 or 500 <= exc.code < 600,
            retry_after_seconds=_retry_after_seconds(
                exc.headers.get("Retry-After") if exc.headers else None
            ),
        ) from None
    except (URLError, TimeoutError):
        raise ModelAPIError(
            "Model API request failed; check network connectivity",
            retryable=True,
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelAPIError(
            "Model API returned an invalid response",
            retryable=True,
        ) from None

    try:
        response_text = (payload["choices"][0]["message"]["content"] or "").strip()
        if response_text.startswith("```"):
            response_text = response_text.strip("`").removeprefix("json").strip()
        result = json.loads(response_text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ModelAPIError(
            "Model API response did not contain valid classification JSON",
            retryable=True,
        ) from None

    return _validate_result(result)


def _validate_result(data):
    if not isinstance(data, dict):
        raise ModelAPIError(
            "Model classification has an invalid structure", retryable=True
        )
    if not isinstance(data.get("is_advertisement"), bool):
        raise ModelAPIError("Model classification has an invalid ad flag", retryable=True)
    if not isinstance(data.get("is_persian"), bool):
        raise ModelAPIError(
            "Model classification has an invalid language flag", retryable=True
        )
    if not isinstance(data.get("advertisement_reason"), str):
        raise ModelAPIError(
            "Model classification is missing advertisement_reason", retryable=True
        )

    result = {
        "is_advertisement": data["is_advertisement"],
        "advertisement_reason": data["advertisement_reason"],
        "is_persian": data["is_persian"],
        "analysis": None,
    }
    if not result["is_advertisement"] and not result["is_persian"]:
        result["analysis"] = _validate_market_analysis(data.get("analysis"))
    return result


def _validate_market_analysis(data):
    levels = {"high", "medium", "low"}
    sentiments = {"bullish", "bearish", "neutral", "mixed"}
    required_strings = (
        "fundamental_analysis",
        "sentiment_analysis",
        "chart_impact",
        "rationale",
    )
    if not isinstance(data, dict):
        raise ModelAPIError("Model analysis has an invalid structure", retryable=True)
    if data.get("impact_level") not in levels:
        raise ModelAPIError("Model analysis has an invalid impact level", retryable=True)
    if data.get("sentiment") not in sentiments:
        raise ModelAPIError("Model analysis has an invalid sentiment", retryable=True)
    for key in ("impact_score", "confidence"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ModelAPIError(
                f"Model analysis has an invalid {key}", retryable=True
            )
    if not isinstance(data.get("affected_assets"), list) or not all(
        isinstance(item, str) for item in data["affected_assets"]
    ):
        raise ModelAPIError("Model analysis has invalid affected assets", retryable=True)
    for key in required_strings:
        if not isinstance(data.get(key), str):
            raise ModelAPIError(
                f"Model analysis is missing {key}", retryable=True
            )
    return data
