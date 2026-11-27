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
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
PUSH_TO_SUBSCRIBERS = os.getenv("PUSH_TO_SUBSCRIBERS", "1") == "1"
MODEL_API_BASE_URL = os.getenv(
    "MODEL_API_BASE_URL", "https://ai.manageit.dev/api/v1"
).rstrip("/")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "manageit/qwen3.8-27b")
MIN_IMPACT_SCORE = int(os.getenv("MIN_IMPACT_SCORE", "50"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_BASE_URL = os.getenv(
    "GEMINI_API_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai",
).rstrip("/")
GEMINI_MIN_INTERVAL_SECONDS = float(os.getenv("GEMINI_MIN_INTERVAL_SECONDS", "7"))
GEMINI_BORDERLINE_RANGE = int(os.getenv("GEMINI_BORDERLINE_RANGE", "15"))

CHANNELS = [
    item.strip().lstrip("@").lower()
    for item in os.getenv(
        "CHANNELS",
        "@forexnews,@bloomberg,@fundcho,@Utofx,@iamusd",
    ).split(",")
    if item.strip()
]
