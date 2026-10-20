"""HelpCrunch webhook authentication and read-only event normalization.

Phase 1 intentionally does not reply to customers.
"""
import hashlib
import hmac
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo


KYIV = ZoneInfo("Europe/Kyiv")
NIGHT_START = time(23, 0)
NIGHT_END = time(8, 0)


def is_night(now=None) -> bool:
    local = (now or datetime.now(KYIV)).astimezone(KYIV).time()
    return local >= NIGHT_START or local < NIGHT_END


def verify_signature(raw_body: bytes, signing_key: str, signature: str) -> bool:
    """HelpCrunch signs the unmodified request body with HMAC-SHA1."""
    if not signing_key or not signature or len(signature) != 40:
        return False
    expected = hmac.new(signing_key.encode("utf-8"), raw_body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def describe_event(raw_body: bytes, application_id: int | None = None, now=None) -> dict:
    """Extract only non-sensitive metadata, never log customer text."""
    payload = json.loads(raw_body)
    if not isinstance(payload, dict):
        raise ValueError("Webhook payload must be an object")
    data = payload.get("eventData")
    if not isinstance(data, dict):
        raise ValueError("Missing eventData")
    message = data.get("message") or {}
    if not isinstance(message, dict):
        raise ValueError("Invalid message")
    app_id = message.get("applicationId", data.get("applicationId"))
    try:
        app_id = int(app_id) if app_id is not None else None
    except (TypeError, ValueError):
        app_id = None
    allowed = app_id is not None and (application_id is None or app_id == int(application_id))
    return {
        "event": payload.get("event"),
        "chat_id": data.get("chat_id"),
        "message_id": message.get("id"),
        "application_id": app_id,
        "target_application": allowed,
        "night": is_night(now),
        "would_process": bool(
            payload.get("event") == "message.chat.customer"
            and allowed
            and is_night(now)
            and data.get("chat_id")
            and message.get("id")
            and isinstance(message.get("text"), str)
            and message.get("text").strip()
        ),
        "mode": "receive-only",
    }
