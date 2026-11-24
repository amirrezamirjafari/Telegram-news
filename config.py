import os
from pathlib import Path


def load_dotenv(path=None):
    path = Path(path or Path(__file__).with_name(".env"))
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
PUSH_TO_SUBSCRIBERS = os.getenv("PUSH_TO_SUBSCRIBERS", "1") == "1"

CHANNELS = [
    item.strip().lstrip("@").lower()
    for item in os.getenv(
        "CHANNELS",
        "@forexnews,@bloomberg,@fundcho,@Utofx,@iamusd",
    ).split(",")
    if item.strip()
]
