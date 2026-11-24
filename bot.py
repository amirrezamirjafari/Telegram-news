import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import config
from database import (
    init_db,
    latest_posts,
    add_subscriber,
    remove_subscriber,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")


def is_authorized(update):
    chat_id = update.effective_chat.id
    if config.OWNER_ID and chat_id != config.OWNER_ID:
        return False
    return True


async def reject(update):
    await update.effective_message.reply_text(
        "دسترسی این ربات فقط برای صاحب آن فعال است."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return
    add_subscriber(update.effective_chat.id)
    await update.effective_message.reply_text(
        "ربات خبر کانال‌ها آماده است.\n"
        "• /latest - آخرین ۱۰ پیام همه کانال‌ها\n"
        "• /latest @channel - آخرین پیام یک کانال\n"
        "• /channels - فهرست کانال‌ها\n"
        "• /unsubscribe - توقف ارسال خودکار",
        parse_mode=ParseMode.MARKDOWN,
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return
    remove_subscriber(update.effective_chat.id)
    await update.effective_message.reply_text(
        "ارسال خودکار پیام‌های جدید متوقف شد."
    )


async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return
    lines = ["کانال‌های پیگیری‌شده:"]
    lines.extend(f"{index}. @{name}" for index, name in enumerate(config.CHANNELS, 1))
    await update.effective_message.reply_text("\n".join(lines))


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return

    channel = None
    if context.args:
        channel = context.args[0].lstrip("@").lower()
        if channel not in {name.lower() for name in config.CHANNELS}:
            await update.effective_message.reply_text(
                "این کانال در فهرست پیگیری‌شده نیست."
            )
            return

    posts = latest_posts(channel=channel, limit=10)
    if not posts:
        await update.effective_message.reply_text(
            "هنوز پیام جدیدی جمع‌آوری نشده است."
        )
        return

    for post_channel, message_id, text, date, link in posts:
        body = text.strip() if text and text.strip() else "(فایل یا رسانه)"
        body = body[:3500]
        message = (
            f"📢 @{html.escape(post_channel)}\n\n"
            f"{html.escape(body)}\n\n"
            f"<a href=\"{html.escape(link or '')}\">مشاهده در کانال</a>"
        )
        await update.effective_message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def main():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    init_db()
    application = Application.builder().token(config.BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("latest", latest))
    application.add_handler(CommandHandler("channels", channels))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.run_polling()


if __name__ == "__main__":
    main()
