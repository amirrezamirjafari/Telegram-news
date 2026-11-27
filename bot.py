import html
import logging

import re

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from database import (
    init_db,
    latest_news,
    add_subscriber,
    remove_subscriber,
    add_channel,
    remove_channel,
    list_channels,
    seed_channels,
)
from processor import analysis_for_latest, format_analysis


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
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
        "• /latest - ۱۰ خبر مالی اخیر، مرتب‌شده بر اساس اثر احتمالی\n"
        "• /latest @channel - آخرین پیام یک کانال\n"
        "• /channels - فهرست کانال‌ها\n"
        "• /addchannel - افزودن کانال جدید\n"
        "• /removechannel - حذف کانال\n"
        "• /unsubscribe - توقف ارسال خودکار\n\n",
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
    lines.extend(f"{index}. @{name}" for index, name in enumerate(list_channels(), 1))
    await update.effective_message.reply_text("\n".join(lines))


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return

    channel = None
    if context.args:
        channel = context.args[0].lstrip("@").lower()
        if channel not in {name.lower() for name in list_channels()}:
            await update.effective_message.reply_text(
                "این کانال در فهرست پیگیری‌شده نیست."
            )
            return

    posts = latest_news(channel=channel, limit=10)
    if not posts:
        await update.effective_message.reply_text(
            "هنوز پیام جدیدی جمع‌آوری نشده است."
        )
        return

    for (
        post_channel,
        message_id,
        text,
        date,
        link,
        analysis_json,
        analysis_status,
        analysis_error,
    ) in posts:
        body = text.strip() if text and text.strip() else "(فایل یا رسانه)"
        body = body[:3000]
        message = (
            f"📢 <b>منبع | @{html.escape(post_channel)}</b>\n\n"
            f"{html.escape(body)}\n\n"
            f"<a href=\"{html.escape(link or '')}\">مشاهده در کانال</a>"
        )
        await update.effective_message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        analysis = analysis_for_latest(analysis_json)
        if analysis:
            await update.effective_message.reply_text(
                format_analysis(post_channel, message_id, analysis),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        elif analysis_status == "failed":
            await update.effective_message.reply_text(
                "⚠️ تحلیل این خبر در دسترس نیست: "
                f"{html.escape(analysis_error or 'خطای نامشخص')}",
                parse_mode=ParseMode.HTML,
            )


_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{3,31}$")

MENU_COMMANDS = [
    BotCommand("start", "شروع و فعال‌سازی ارسال خودکار"),
    BotCommand("latest", "۱۰ خبر مالی مهم اخیر"),
    BotCommand("channels", "فهرست کانال‌های منبع"),
    BotCommand("addchannel", "افزودن کانال منبع"),
    BotCommand("removechannel", "حذف کانال منبع"),
    BotCommand("unsubscribe", "توقف ارسال خودکار"),
]


def parse_username(raw):
    value = re.sub(r"^(?:https?://)?t\.me/", "", (raw or "").strip().lower())
    value = value.lstrip("@")
    return value if _USERNAME_RE.match(value) else None


async def _add_channel(update, raw):
    username = parse_username(raw)
    if not username:
        await update.effective_message.reply_text(
            "نام کانال معتبر نیست. فقط حروف انگلیسی، عدد و _ (۴ تا ۳۲ کاراکتر)."
        )
        return
    if add_channel(username):
        await update.effective_message.reply_text(
            f"✅ @{username} اضافه شد. در دور بعدی جمع‌آوری فعال می‌شود."
        )
    else:
        await update.effective_message.reply_text(
            f"@{username} از قبل در فهرست است."
        )


async def _remove_channel(update, raw):
    username = parse_username(raw)
    if username and remove_channel(username):
        text = f"🗑 @{username} حذف شد."
    else:
        text = "این کانال در فهرست نیست."
    await update.effective_message.reply_text(text)


async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return
    if context.args:
        await _add_channel(update, context.args[0])
        return
    context.user_data["awaiting"] = "add"
    await update.effective_message.reply_text(
        "نام کانال را بفرست؛ مثلاً @forexnews"
    )


async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject(update)
        return
    if context.args:
        await _remove_channel(update, context.args[0])
        return
    names = list_channels()
    if not names:
        await update.effective_message.reply_text("فهرست کانال‌ها خالی است.")
        return
    keyboard = [
        [InlineKeyboardButton(f"❌ @{name}", callback_data=f"rm:{name}")]
        for name in names
    ]
    await update.effective_message.reply_text(
        "کدام کانال حذف شود؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def remove_channel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(update):
        return
    await _remove_channel(update, query.data.removeprefix("rm:"))


async def plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if context.user_data.pop("awaiting", None) == "add":
        await _add_channel(update, update.effective_message.text)


async def post_init(application):
    await application.bot.set_my_commands(MENU_COMMANDS)


def main():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    init_db()
    seed_channels(config.CHANNELS)
    application = (
        Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("latest", latest))
    application.add_handler(CommandHandler("channels", channels))
    application.add_handler(CommandHandler("addchannel", add_channel_command))
    application.add_handler(CommandHandler("removechannel", remove_channel_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CallbackQueryHandler(remove_channel_button, pattern=r"^rm:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_text))
    application.run_polling()


if __name__ == "__main__":
    main()
