import hashlib
import re
import unicodedata

from database import normalize_for_comparison


_FINANCIAL_TERMS = (
    r"\bforex\b", r"\bfx\b", r"\bcurrenc(?:y|ies)\b",
    r"\bexchange rate\b", r"\bcentral bank\b", r"\bbank(?:s|ing)?\b",
    r"\binterest rates?\b", r"\binflation\b", r"\b(?:cpi|pce)\b",
    r"\bgdp\b", r"\beconom(?:y|ic|ics)\b", r"\bstocks?\b",
    r"\bequities\b", r"\bshares?\b", r"\bstock market\b",
    r"\bbonds?\b", r"\btreasur(?:y|ies)\b", r"\byields?\b",
    r"\b(?:fed|federal reserve|ecb|boe|boj|rba|snb)\b",
    r"\bmonetary policy\b", r"\bpayrolls?\b", r"\bunemployment\b",
    r"\bjobs report\b", r"\bcommodity\b", r"\bcommodities\b",
    r"\bgold\b", r"\bcrude oil\b", r"\bbitcoin\b", r"\bcrypto(?:currency)?\b",
)
_FINANCIAL_PATTERN = re.compile("|".join(_FINANCIAL_TERMS), re.IGNORECASE)
_PERSIAN_TERMS = (
    "فارکس", "بازار ارز", "نرخ ارز", "ارز", "دلار", "یورو", "پوند",
    "ین ژاپن", "بانک مرکزی", "بانک", "نرخ بهره", "تورم",
    "شاخص قیمت", "تولید ناخالص داخلی", "اقتصاد", "بورس", "سهام",
    "اوراق", "بازده اوراق", "فدرال رزرو", "طلا", "نفت", "بیت‌کوین",
    "بیت کوین", "ارز دیجیتال", "نقدینگی", "سیاست پولی", "اشتغال",
)


def normalize_news(text):
    normalized = normalize_for_comparison(text)
    return normalized


def is_financially_relevant(text):
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    normalized = normalized.replace("ي", "ی").replace("ك", "ک")
    return bool(
        _FINANCIAL_PATTERN.search(normalized)
        or any(term in normalized for term in _PERSIAN_TERMS)
    )


def fingerprint(text):
    normalized = normalize_news(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
