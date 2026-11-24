# Telegram News Collector

A private Telegram news collector that reads the latest posts from five or more
configured channels and sends them through a Telegram bot.

## How it works

- `collector.py` uses a Telegram user-account session (Telethon) to read channel
  posts. Telegram Bot API alone cannot read arbitrary channels.
- `bot.py` provides `/latest`, `/channels`, `/start`, and `/unsubscribe`.
- Posts are stored locally in SQLite and deduplicated by channel and message ID.
- One user session can read public channels it has subscribed to, and private
  channels it is allowed to join.

## Setup

1. Create a Telegram application at https://my.telegram.org/apps.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
   `TELEGRAM_PHONE`, `OWNER_ID`, and `CHANNELS`.
4. Install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. Log in once to create the local Telethon session:

   ```bash
   python login.py
   ```

6. Run the bot and collector in separate terminals:

   ```bash
   python bot.py
   python collector.py
   ```

The default channels are `@forexnews`, `@bloomberg`, `@fundcho`, `@Utofx`,
and `@iamusd`. Override them with a comma-separated `CHANNELS` value.

Keep `.env`, `*.session`, and `news.db` private and untracked.
