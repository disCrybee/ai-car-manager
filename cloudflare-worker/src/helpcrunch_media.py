"""Recognize media without downloading untrusted customer URLs."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
MEDIA_TEXT = re.compile(
    r'<(?:img|video|audio)\b|https?://[^\s<>"\']+\.(?:png|jpe?g|webp|gif|heic|mp4|mov)(?:[?#][^\s<>]*)?(?=\s|$|[<>"\'])',
    re.IGNORECASE,
)


def has_media(message):
    if not isinstance(message, dict):
        return False
    if any(message.get(key) for key in ("attachment", "attachments", "attachmentId")):
        return True
    if message.get("type") in ("image", "video", "audio", "file", "attachment"):
        return True
    text = message.get("text")
    return isinstance(text, str) and bool(MEDIA_TEXT.search(text))


def media_reply(now=None, *, phone_received=False):
    local = (now or datetime.now(KYIV)).astimezone(KYIV)
    day = "завтра" if local.hour >= 23 else "сьогодні"
    opening = "Дякуємо за вкладення! Наші менеджери зараз не онлайн. "
    if phone_received:
        return opening + f"Ваш номер уже отримано — менеджер зв’яжеться з Вами {day} в робочий час та уточнить деталі."
    return opening + f"Залиште, будь ласка, Ваш номер телефону — менеджер зв’яжеться з Вами {day} в робочий час та уточнить деталі."
