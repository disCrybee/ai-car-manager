"""Persist confirmed AI message IDs per real HelpCrunch chat/site.

Only add IDs returned by HelpCrunch after a successful send. Never infer ID
from timestamps or message body; unknown IDs must trigger manual handoff.
"""
import json

GUARD_OFFSET = 2000000000

def guard_key(chat_id, application_id):
    chat, app = int(chat_id), int(application_id)
    if chat <= 0 or not 0 < app < 1000000000:
        raise ValueError("Invalid HelpCrunch chat/site")
    return chat, -(GUARD_OFFSET + app)

async def load_bot_message_ids(db, chat_id, application_id):
    chat, app = guard_key(chat_id, application_id)
    row = await db.prepare(
        "SELECT state_json FROM hc_dialog_state WHERE chat_id=? AND application_id=?"
    ).bind(chat, app).first()
    if not row:
        return []
    raw = row.get("state_json") if isinstance(row, dict) else getattr(row, "state_json", None)
    data = json.loads(raw or "{}")
    values = data.get("bot_message_ids", [])
    if not isinstance(values, list) or any(type(x) is not int or x <= 0 for x in values):
        raise ValueError("Invalid stored AI message IDs")
    return values[-100:]

async def record_bot_message_id(db, chat_id, application_id, message_id):
    mid = int(message_id)
    if mid <= 0:
        raise ValueError("No confirmed HelpCrunch message ID")
    existing = await load_bot_message_ids(db, chat_id, application_id)
    ids = (existing + [mid])[-100:]
    chat, app = guard_key(chat_id, application_id)
    payload = json.dumps({"bot_message_ids": ids}, separators=(",", ":"))
    await db.prepare(
        "INSERT INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?) "
        "ON CONFLICT(chat_id,application_id) DO UPDATE SET "
        "state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP"
    ).bind(chat, app, payload).run()
