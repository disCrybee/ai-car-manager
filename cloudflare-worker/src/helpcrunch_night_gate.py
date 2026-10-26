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
