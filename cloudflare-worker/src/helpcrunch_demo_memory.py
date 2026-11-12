"""Isolated demo dialogue history in existing D1 schema.

Negative application_id is reserved for demo sessions. Real HelpCrunch IDs
are positive and cannot address these rows via the production store API.
"""
import hashlib
import hmac
import json
import re

DEMO_APPLICATION = -1
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,48}$")


def demo_chat_id(session: str, signing_secret: str) -> int:
    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
        raise ValueError("Invalid demo session")
    if not signing_secret:
        raise ValueError("Demo signing secret required")
    digest = hmac.new(signing_secret.encode(), session.encode(), hashlib.sha256).digest()
    # Keep identifiers within JS-safe integer range for Python Workers D1 .bind().
    return -(int.from_bytes(digest[:6], "big") + 1)


async def load_demo_history(db, session: str, secret: str) -> list:
    chat_id = demo_chat_id(session, secret)
    row = await db.prepare(
        "SELECT state_json FROM hc_dialog_state WHERE chat_id = ? AND application_id = ?"
    ).bind(chat_id, DEMO_APPLICATION).first()
    if not row:
        return []
    raw = row.get("state_json") if isinstance(row, dict) else getattr(row, "state_json", None)
    data = json.loads(raw) if raw else {}
    history = data.get("history", [])
    if not isinstance(history, list):
        raise ValueError("Invalid stored demo history")
    return history[-12:]


async def save_demo_history(db, session: str, secret: str, history: list):
    chat_id = demo_chat_id(session, secret)
    safe = history[-12:]
    if any(not isinstance(x, dict) or x.get("role") not in ("user", "assistant")
           or not isinstance(x.get("content"), str) or len(x["content"]) > 1500 for x in safe):
        raise ValueError("Invalid demo dialogue history")
    payload = json.dumps({"history": safe}, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 16000:
        raise ValueError("Demo history is too large")
    await db.prepare(
        "INSERT INTO hc_dialog_state(chat_id, application_id, state_json) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, application_id) DO UPDATE SET "
        "state_json = excluded.state_json, updated_at = CURRENT_TIMESTAMP"
    ).bind(chat_id, DEMO_APPLICATION, payload).run()
