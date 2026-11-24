import asyncio

from telethon import TelegramClient

import config


async def main():
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        raise RuntimeError(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first"
        )
    client = TelegramClient(
        "collector",
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    await client.start(phone=config.TELEGRAM_PHONE or None)
    me = await client.get_me()
    print(f"Login successful: {me.username or me.id}")


if __name__ == "__main__":
    asyncio.run(main())
