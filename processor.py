import asyncio
import html
import json
import logging
import time

from telegram.constants import ParseMode

import database
from model_api import ModelAPIError, analyze_news
from news_filter import fingerprint, is_financially_relevant, normalize_news


logger = logging.getLogger("processor")
_IMPACT_LABELS = {"high": "زیاد", "medium": "متوسط", "low": "کم"}
_SENTIMENT_LABELS = {
    "bullish": "مثبت",
    "bearish": "منفی",
    "neutral": "خنثی",
    "mixed": "ترکیبی",
}
MAX_ANALYSIS_ATTEMPTS = 5
_BASE_RETRY_DELAY_SECONDS = 2
_MAX_RETRY_DELAY_SECONDS = 3600
_MIN_MODEL_REQUEST_INTERVAL_SECONDS = 1
_MODEL_REQUEST_LOCK = asyncio.Lock()
_NEXT_MODEL_REQUEST_AT = 0.0


def _retry_delay(attempt, error):
    delay = error.retry_after_seconds
    if delay is None:
        delay = _BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
    return max(1, min(_MAX_RETRY_DELAY_SECONDS, delay))


async def _analyze_with_throttle(text, channel, attempt):
    global _NEXT_MODEL_REQUEST_AT

    async with _MODEL_REQUEST_LOCK:
        delay = _NEXT_MODEL_REQUEST_AT - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            result = await asyncio.to_thread(analyze_news, text, channel)
        except ModelAPIError as exc:
            delay = (
                _retry_delay(attempt, exc)
                if exc.retryable
                else _MIN_MODEL_REQUEST_INTERVAL_SECONDS
            )
            _NEXT_MODEL_REQUEST_AT = max(
                _NEXT_MODEL_REQUEST_AT,
                time.monotonic() + delay,
            )
            raise
        _NEXT_MODEL_REQUEST_AT = max(
            _NEXT_MODEL_REQUEST_AT,
            time.monotonic() + _MIN_MODEL_REQUEST_INTERVAL_SECONDS,
        )
        return result


async def _broadcast_raw_once(channel, message_id, text, link, bot, raw_sent):
    if not raw_sent:
        await broadcast_raw(channel, message_id, text, link, bot)
        database.mark_raw_sent(channel, message_id)
    return True


async def process_post(
    channel, message_id, text, date, link, bot, notify, retry_failed=True
):
    is_new = database.save_post(channel, message_id, text, date, link)
    raw_sent = False
    if not is_new:
        current = database.post_processing_status(channel, message_id)
        if not current:
            return "existing"
        status = current[1]
        raw_sent = bool(current[5])
        if status == "pending":
            notify = False
        elif status == "failed":
            if (
                not retry_failed
                or current[3] >= MAX_ANALYSIS_ATTEMPTS
                or not current[4]
                or current[4] > database.utc_now()
            ):
                return "existing"
        else:
            return "existing"

    relevant = is_financially_relevant(text)
    normalized = normalize_news(text)
    database.mark_post_relevant(
        channel, message_id, relevant, fingerprint(text) if normalized else None
    )
    if not relevant:
        logger.info("Filtered non-financial post @%s/%s", channel, message_id)
        return "filtered"

    duplicate = database.find_duplicate(
        normalized,
        fingerprint(text),
        channel,
        message_id,
    )
    if duplicate:
        database.mark_duplicate(channel, message_id, *duplicate)
        logger.info(
            "Skipped duplicate @%s/%s; matches @%s/%s (%.2f)",
            channel,
            message_id,
            duplicate[0],
            duplicate[1],
            duplicate[2],
        )
        return "duplicate"

    while True:
        attempt = database.begin_analysis_attempt(
            channel, message_id, MAX_ANALYSIS_ATTEMPTS
        )
        if attempt is None:
            return "existing"
        try:
            result = await _analyze_with_throttle(text, channel, attempt)
            break
        except ModelAPIError as exc:
            delay = (
                _retry_delay(attempt, exc)
                if exc.retryable and attempt < MAX_ANALYSIS_ATTEMPTS
                else None
            )
            database.save_analysis_error(
                channel,
                message_id,
                str(exc),
                retry_after_seconds=delay,
            )
            if delay is not None:
                logger.warning(
                    "Model request failed for @%s/%s; retry %s/%s in %.1fs",
                    channel,
                    message_id,
                    attempt + 1,
                    MAX_ANALYSIS_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            logger.warning(
                "Model analysis failed for @%s/%s after %s attempt(s): %s",
                channel,
                message_id,
                attempt,
                exc,
            )
            if notify:
                raw_sent = await _broadcast_raw_once(
                    channel, message_id, text, link, bot, raw_sent
                )
                await broadcast_analysis_error(channel, message_id, str(exc), bot)
            return "analysis_failed"
        except Exception as exc:
            error = f"Model analysis failed ({type(exc).__name__})"
            database.save_analysis_error(channel, message_id, error)
            logger.exception(
                "Unexpected model analysis failure for @%s/%s",
                channel,
                message_id,
            )
            if notify:
                raw_sent = await _broadcast_raw_once(
                    channel, message_id, text, link, bot, raw_sent
                )
                await broadcast_analysis_error(channel, message_id, error, bot)
            return "analysis_failed"

    if result["is_advertisement"]:
        database.mark_post_advertisement(channel, message_id)
        logger.info(
            "Filtered advertisement @%s/%s: %s",
            channel,
            message_id,
            result["advertisement_reason"][:200],
        )
        return "advertisement"

    if result["is_persian"]:
        database.mark_analysis_not_required(channel, message_id)
        if notify:
            await _broadcast_raw_once(
                channel, message_id, text, link, bot, raw_sent
            )
        return "analysis_not_required"

    analysis = result["analysis"]
    if notify:
        raw_sent = await _broadcast_raw_once(
            channel, message_id, text, link, bot, raw_sent
        )
    database.save_analysis(channel, message_id, analysis)
    if notify:
        await broadcast_analysis(channel, message_id, analysis, bot)
    return "processed"


def format_analysis(channel, message_id, analysis):
    assets = analysis["affected_assets"] or ["مشخص نشده"]
    body = (
        f"🧠 <b>تحلیل Qwen | @{html.escape(channel)} #{message_id}</b>\n"
        f"⚡ اثر احتمالی: <b>{_IMPACT_LABELS[analysis['impact_level']]}</b> "
        f"({analysis['impact_score']}/100)\n"
        f"📊 سنتیمنت: <b>{_SENTIMENT_LABELS[analysis['sentiment']]}</b>\n"
        f"💱 دارایی‌های مرتبط: {html.escape(', '.join(assets)[:500])}\n\n"
        f"🧭 <b>تحلیل فاندامنتال</b>\n"
        f"{html.escape(analysis['fundamental_analysis'][:900])}\n\n"
        f"💬 <b>تحلیل سنتیمنتال</b>\n"
        f"{html.escape(analysis['sentiment_analysis'][:700])}\n\n"
        f"📈 <b>اثر احتمالی بر چارت</b>\n"
        f"{html.escape(analysis['chart_impact'][:900])}\n\n"
        f"🎯 اطمینان: {analysis['confidence']}٪ — "
        f"{html.escape(analysis['rationale'][:500])}\n"
        "⚠️ این تحلیل توصیه سرمایه گذاری نیست."
    )
    return body[:4000]


async def _broadcast(message, bot):
    for chat_id in database.active_subscribers():
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning(
                "Telegram delivery failed (%s)", type(exc).__name__
            )


async def broadcast_raw(channel, message_id, text, link, bot):
    body = (text or "").strip() or "(فایل یا رسانه)"
    message = (
        f"📢 <b>منبع | @{html.escape(channel)}</b>\n\n"
        f"{html.escape(body[:3000])}\n\n"
        f'<a href="{html.escape(link or "", quote=True)}">مشاهده در کانال</a>'
    )
    await _broadcast(message, bot)


async def broadcast_analysis(channel, message_id, analysis, bot):
    await _broadcast(format_analysis(channel, message_id, analysis), bot)


async def broadcast_analysis_error(channel, message_id, error, bot):
    message = (
        f"⚠️ <b>تحلیل خبر @{html.escape(channel)} #{message_id} انجام نشد.</b>\n"
        f"{html.escape(error[:500])}\n"
        "منبع در آرشیو ذخیره شده است."
    )
    await _broadcast(message, bot)


def analysis_for_latest(raw_json):
    if not raw_json:
        return None
    try:
        return json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        logger.error("Stored analysis JSON is invalid")
        return None
