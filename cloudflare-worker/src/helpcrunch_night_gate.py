"""Night rollout gate. All-chat sending remains disabled until reviewed.

Safety requirements before connecting to outbound:
- exact 23:00–08:00 Europe/Kyiv time, including DST
- per-chat isolated state and message deduplication
- manual agent participation suppresses replies
- per-application brand configuration
"""
from helpcrunch_webhook import is_night

def eligible_night_event(metadata, enabled, *, now=None):
    if enabled != "true" or not is_night(now):
        return False
    if not isinstance(metadata, dict):
        return False
    try:
        return (
            metadata.get("event") == "message.chat.customer"
            and int(metadata.get("chat_id") or 0) > 0
            and int(metadata.get("message_id") or 0) > 0
            and int(metadata.get("application_id") or 0) > 0
        )
    except (ValueError, TypeError):
        return False


def night_preview_decision(metadata, enabled, brand, *, now=None):
    """Non-sending decision for rollout auditing; never authorizes outbound alone."""
    if enabled != "true":
        return {"eligible": False, "reason": "disabled"}
    if not eligible_night_event(metadata, enabled, now=now):
        return {"eligible": False, "reason": "outside-window-or-invalid-event"}
    return {"eligible": True, "reason": "night-preview-only", "brand": brand or "neutral"}


def live_chat_allowed(chat_id, enabled, allowed_chat_id):
    """Live sends require exact operator-approved single-chat allowlist."""
    try:
        return (enabled == "true" and int(chat_id) > 0
                and str(chat_id) == str(allowed_chat_id)
                and str(allowed_chat_id).isdigit())
    except (TypeError, ValueError):
        return False
