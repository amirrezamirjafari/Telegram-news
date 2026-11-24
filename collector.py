import asyncio
import html
import logging

from telethon import TelegramClient, events
from telethon.tl.types import Channel
from telegram import Bot
from telegram.constants import ParseMode

import config
from database import (
    init_db,
    save_post,
    latest_posts,
    active_subscribers,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("collector")


def channel_link(channel, message_id):
    if message_id:
        return f"https://t.me/{channel}/{message_id}"
    return f"https://t.me/{channel}"


def post_text(channel, message_id, text):
    link = channel_link(channel, message_id)
    body = text.strip() if text and text.strip() else "(فایل یا رسانه)"
    if len(body) > 3500:
        body = body[:3497] + "..."
    return (
        f"📢 @{html.escape(channel)}\n\n"
        f"{html.escape(body)}\n\n"
        f"<a href=\"{html.escape(link)}\">مشاهده در کانال</a>"
    )


async def push_post(channel, message_id, text, bot):
    if not config.PUSH_TO_SUBSCRIBERS:
        return
    message = post_text(channel, message_id, text)
    for chat_id in active_subscribers():
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning("Could not send post to %s: %s", chat_id, exc)


async def collect_once(client, bot, push):
    for username in config.CHANNELS:
        try:
            entity = await client.get_entity(username)
            if not isinstance(entity, Channel):
                logger.warning("%s is not a Telegram channel", username)
                continue

            messages = await client.get_messages(entity, limit=10)
            for message in reversed(messages):
                text = message.text or message.message or ""
                date = message.date.isoformat() if message.date else ""
                link = channel_link(username, message.id)
                is_new = save_post(username, message.id, text, date, link)
                if is_new and push:
                    await push_post(username, message.id, text, bot)
        except Exception as exc:
            logger.exception("Failed to collect @%s: %s", username, exc)


async def main():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        raise RuntimeError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are required"
        )
    if not config.CHANNELS:
        raise RuntimeError("CHANNELS must contain at least one channel")

    init_db()
    bot = Bot(token=config.BOT_TOKEN)
    client = TelegramClient(
        "collector",
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )

    await client.start(phone=config.TELEGRAM_PHONE or None)
    me = await client.get_me()
    logger.info("Collector logged in as %s", me.username or me.id)

    allowed = set(config.CHANNELS)

    @client.on(events.NewMessage)
    async def on_new_message(event):
        if not event.is_channel or not event.chat:
            return
        username = getattr(event.chat, "username", None)
        if not username or username.lower() not in allowed:
            return
        username = username.lower()
        text = event.raw_text or ""
        date = event.message.date.isoformat() if event.message.date else ""
        link = channel_link(username, event.message.id)
        is_new = save_post(username, event.message.id, text, date, link)
        if is_new:
            await push_post(username, event.message.id, text, bot)

    await collect_once(client, bot, push=False)

    while True:
        await collect_once(client, bot, push=True)
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
