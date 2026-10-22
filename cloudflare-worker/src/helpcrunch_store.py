"""HelpCrunch-only D1 persistence, separate from legacy bot storage.

Application + chat ID identify state, so different website widgets cannot collide.
Webhook event IDs are used for deduplication and must be stable across retries.
"""
import json


def _positive_int(value, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {label}") from None
    if number <= 0:
        raise ValueError(f"Invalid {label}")
    return number


async def load_dialog(db, chat_id, application_id):
    chat_id = _positive_int(chat_id, "chat_id")
    application_id = _positive_int(application_id, "application_id")
    result = await db.prepare(
        "SELECT state_json FROM hc_dialog_state WHERE chat_id = ? AND application_id = ?"
    ).bind(chat_id, application_id).first()
    if not result:
        return None
    raw = result.get("state_json") if isinstance(result, dict) else getattr(result, "state_json", None)
    return json.loads(raw) if raw else None


async def save_dialog(db, chat_id, application_id, state):
    chat_id = _positive_int(chat_id, "chat_id")
    application_id = _positive_int(application_id, "application_id")
    if not isinstance(state, dict):
        raise ValueError("Dialog state must be an object")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 32000:
        raise ValueError("Dialog state too large")
    await db.prepare(
        "INSERT INTO hc_dialog_state(chat_id, application_id, state_json) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, application_id) DO UPDATE SET "
        "state_json = excluded.state_json, updated_at = CURRENT_TIMESTAMP"
    ).bind(chat_id, application_id, payload).run()


async def claim_event(db, event_key, chat_id, application_id):
    """Insert-if-new. Caller must retry transient errors, never assume success."""
    chat_id = _positive_int(chat_id, "chat_id")
    application_id = _positive_int(application_id, "application_id")
    if not isinstance(event_key, str) or not 1 <= len(event_key) <= 180:
        raise ValueError("Invalid event key")
    result = await db.prepare(
        "INSERT OR IGNORE INTO hc_processed_events(event_key, chat_id, application_id) "
        "VALUES (?, ?, ?)"
    ).bind(event_key, chat_id, application_id).run()
    meta = result.get("meta", {}) if isinstance(result, dict) else getattr(result, "meta", None)
    changes = meta.get("changes", 0) if isinstance(meta, dict) else getattr(meta, "changes", 0)
    return changes == 1


async def commit_dialog_event(db, event_key, chat_id, application_id, state):
    """Atomically claim an event and save state; fail closed on D1 errors.

    Returns False only if the exact event key already exists. Any other D1
    failure is re-raised. This avoids consuming an event without saving state.
    """
    chat_id = _positive_int(chat_id, "chat_id")
    application_id = _positive_int(application_id, "application_id")
    if not isinstance(event_key, str) or not 1 <= len(event_key) <= 180:
        raise ValueError("Invalid event key")
    if not isinstance(state, dict):
        raise ValueError("Dialog state must be an object")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 32000:
        raise ValueError("Dialog state too large")
    exists = await db.prepare(
        "SELECT event_key FROM hc_processed_events WHERE event_key = ?"
    ).bind(event_key).first()
    if exists:
        return False
    try:
        await db.batch([
            db.prepare(
                "INSERT INTO hc_processed_events(event_key, chat_id, application_id) "
                "VALUES (?, ?, ?)"
            ).bind(event_key, chat_id, application_id),
            db.prepare(
                "INSERT INTO hc_dialog_state(chat_id, application_id, state_json) "
                "VALUES (?, ?, ?) ON CONFLICT(chat_id, application_id) DO UPDATE SET "
                "state_json = excluded.state_json, updated_at = CURRENT_TIMESTAMP"
            ).bind(chat_id, application_id, payload),
        ])
    except Exception:
        # In a race, only the loser with a committed matching event is duplicate.
        # Never swallow other failures or pretend persistence succeeded.
        exists = await db.prepare(
            "SELECT event_key FROM hc_processed_events WHERE event_key = ?"
        ).bind(event_key).first()
        if exists:
            return False
        raise
    return True
