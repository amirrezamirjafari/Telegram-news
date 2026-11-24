import asyncio
import logging

from telethon import TelegramClient, events
from telethon.tl.types import Channel
from telegram import Bot

import config
import database
from database import init_db
from processor import MAX_ANALYSIS_ATTEMPTS, process_post


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("collector")


def channel_link(channel, message_id):
    if message_id:
        return f"https://t.me/{channel}/{message_id}"
    return f"https://t.me/{channel}"


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
                await process_post(
                    username,
                    message.id,
                    text,
                    date,
                    link,
                    bot,
                    notify=push and config.PUSH_TO_SUBSCRIBERS,
                    retry_failed=push,
                )
        except Exception as exc:
            logger.exception("Failed to collect @%s: %s", username, exc)


async def retry_failed_posts(bot):
    posts = database.retryable_posts(MAX_ANALYSIS_ATTEMPTS)
    for channel, message_id, text, date, link in posts:
        await process_post(
            channel,
            message_id,
            text,
            date,
            link,
            bot,
            notify=config.PUSH_TO_SUBSCRIBERS,
        )


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
    database.recover_interrupted_analyses(MAX_ANALYSIS_ATTEMPTS)
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
        await process_post(
            username,
            event.message.id,
            text,
            date,
            link,
            bot,
            notify=config.PUSH_TO_SUBSCRIBERS,
        )

    await collect_once(client, bot, push=False)
    await retry_failed_posts(bot)

    while True:
        await collect_once(client, bot, push=True)
        await retry_failed_posts(bot)
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
