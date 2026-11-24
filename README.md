# Telegram News Analysis Bot

A private Telegram news collector that filters configured channels for financial
news, removes repeat stories, and delivers raw news followed by a separate
Qwen analysis.

## How it works

- `collector.py` uses a Telegram user-account session (Telethon) to read channel
  posts. Telegram Bot API alone cannot read arbitrary channels.
- `bot.py` provides `/latest`, `/channels`, `/start`, and `/unsubscribe`.
- All collected posts are archived in SQLite. Financial relevance is tagged;
  near-identical financial posts are linked to the earlier story and not sent
  for repeat analysis.
- Relevant news is delivered raw first, then with Qwen's impact ranking,
  fundamental and sentiment analysis, and a cautious discussion of potential
  chart impact. Analyses are archived with the original post.
- One user session can read public channels it has subscribed to, and private
  channels it is allowed to join.

## Setup

1. Create a Telegram application at https://my.telegram.org/apps.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
   `TELEGRAM_PHONE`, `OWNER_ID`, and `CHANNELS`.
4. Set `MODEL_API_KEY` to your ManageIT API key in `.env`. The default endpoint
   is `https://ai.manageit.dev/api/v1` and the default model is
   `manageit/qwen3.8-27b`; override them with `MODEL_API_BASE_URL` and
   `MODEL_NAME` if needed. The collector still archives and delivers relevant
   raw posts when the key is absent; it records and reports that analysis
   could not be completed.
5. Install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

6. Log in once to create the local Telethon session:

   ```bash
   python login.py
   ```

7. Run the bot and collector in separate terminals:

   ```bash
   python bot.py
   python collector.py
   ```

The default channels are `@forexnews`, `@bloomberg`, `@fundcho`, `@Utofx`,
and `@iamusd`. Override them with a comma-separated `CHANNELS` value.

Keep `.env`, `*.session`, and `news.db` private and untracked.

Qwen analysis is informational and probabilistic, not a guaranteed market
prediction or personalized investment advice. API errors are recorded against
the post and do not stop collection.
