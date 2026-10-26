"""Isolated night-mode history by real HelpCrunch application and chat.

No shared demo session. This module does not send any messages.
"""
import json

NIGHT_HISTORY_APPLICATION_OFFSET = 1000000000

def night_state_key(chat_id, application_id):
    chat, app = int(chat_id), int(application_id)
    if chat <= 0 or app <= 0 or app >= NIGHT_HISTORY_APPLICATION_OFFSET:
        raise ValueError("Invalid HelpCrunch chat/application")
    return chat, -(NIGHT_HISTORY_APPLICATION_OFFSET + app)

async def load_night_history(db, chat_id, application_id):
    chat, app = night_state_key(chat_id, application_id)
    row = await db.prepare(
        "SELECT state_json FROM hc_dialog_state WHERE chat_id=? AND application_id=?"
    ).bind(chat, app).first()
    if not row:
        return []
    raw = row.get("state_json") if isinstance(row, dict) else getattr(row, "state_json", None)
    data = json.loads(raw or "{}")
    turns = data.get("history", [])
    if not isinstance(turns, list):
        raise ValueError("Invalid night history")
    return turns[-12:]

async def save_night_history(db, chat_id, application_id, history):
    chat, app = night_state_key(chat_id, application_id)
    turns = history[-12:]
    if any(not isinstance(t, dict) or t.get("role") not in ("user", "assistant")
           or not isinstance(t.get("content"), str) or len(t["content"]) > 1500 for t in turns):
        raise ValueError("Invalid night history")
    payload = json.dumps({"history": turns}, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 16000:
        raise ValueError("Night history too large")
    await db.prepare(
        "INSERT INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?) "
        "ON CONFLICT(chat_id,application_id) DO UPDATE SET "
        "state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP"
    ).bind(chat, app, payload).run()
