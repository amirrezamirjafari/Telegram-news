import asyncio
import html
import json
import logging

from telegram.constants import ParseMode

import database
from gemini import GeminiAPIError, analyze_news
from news_filter import fingerprint, is_financially_relevant, normalize_news


logger = logging.getLogger("processor")
_IMPACT_LABELS = {"high": "زیاد", "medium": "متوسط", "low": "کم"}
_SENTIMENT_LABELS = {
    "bullish": "مثبت",
    "bearish": "منفی",
    "neutral": "خنثی",
    "mixed": "ترکیبی",
}


async def process_post(channel, message_id, text, date, link, bot, notify):
    is_new = database.save_post(channel, message_id, text, date, link)
    if not is_new:
        current = database.post_processing_status(channel, message_id)
        if not current or current[1] != "pending":
            return "existing"
        notify = False

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

    if notify:
        await broadcast_raw(channel, message_id, text, link, bot)

    try:
        analysis = await asyncio.to_thread(analyze_news, text, channel)
    except GeminiAPIError as exc:
        database.save_analysis_error(channel, message_id, str(exc))
        logger.warning(
            "Gemini analysis failed for @%s/%s: %s", channel, message_id, exc
        )
        if notify:
            await broadcast_analysis_error(channel, message_id, str(exc), bot)
        return "analysis_failed"
    except Exception as exc:
        error = f"Gemini analysis failed ({type(exc).__name__})"
        database.save_analysis_error(channel, message_id, error)
        logger.exception("Unexpected analysis failure for @%s/%s", channel, message_id)
        if notify:
            await broadcast_analysis_error(channel, message_id, error, bot)
        return "analysis_failed"

    database.save_analysis(channel, message_id, analysis)
    if notify:
        await broadcast_analysis(channel, message_id, analysis, bot)
    return "processed"


def format_analysis(channel, message_id, analysis):
    assets = analysis["affected_assets"] or ["مشخص نشده"]
    body = (
        f"🧠 <b>تحلیل Gemini | @{html.escape(channel)} #{message_id}</b>\n"
        f"اولویت اثر: <b>{_IMPACT_LABELS[analysis['impact_level']]}</b> "
        f"({analysis['impact_score']}/100)\n"
        f"سنتیمنت: <b>{_SENTIMENT_LABELS[analysis['sentiment']]}</b>\n"
        f"دارایی‌های مرتبط: {html.escape(', '.join(assets)[:500])}\n\n"
        f"<b>تحلیل فاندامنتال</b>\n"
        f"{html.escape(analysis['fundamental_analysis'][:900])}\n\n"
        f"<b>تحلیل سنتیمنتال</b>\n"
        f"{html.escape(analysis['sentiment_analysis'][:700])}\n\n"
        f"<b>اثر احتمالی بر چارت</b>\n"
        f"{html.escape(analysis['chart_impact'][:900])}\n\n"
        f"اطمینان: {analysis['confidence']}٪ — "
        f"{html.escape(analysis['rationale'][:500])}\n"
        "این تحلیل احتمالی و صرفاً اطلاع‌رسانی است؛ توصیه سرمایه‌گذاری نیست."
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
        f"📢 <b>خبر خام | @{html.escape(channel)}</b>\n\n"
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
        "خبر خام در آرشیو ذخیره شده است."
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
