"""Per-chat completion flag for night assistant."""
import json
from helpcrunch_bot_message_ids import guard_key

def night_state_key(chat_id, application_id):
    chat, key = guard_key(chat_id, application_id)
    return chat, key - 1000000000

async def get_night_completion(db, chat_id, application_id):
    chat, key = night_state_key(chat_id, application_id)
    row=await db.prepare("SELECT state_json FROM hc_dialog_state WHERE chat_id=? AND application_id=?").bind(chat,key).first()
    if not row:return False
    raw=row.get("state_json") if isinstance(row,dict) else getattr(row,"state_json",None)
    data=json.loads(raw or "{}")
    return bool(data.get("completed",False))

async def set_night_completion(db, chat_id, application_id, completed):
    chat, key=night_state_key(chat_id,application_id)
    row=await db.prepare("SELECT state_json FROM hc_dialog_state WHERE chat_id=? AND application_id=?").bind(chat,key).first()
    raw=(row.get("state_json") if isinstance(row,dict) else getattr(row,"state_json",None)) if row else None
    data=json.loads(raw or "{}")
    data["completed"]=bool(completed)
    await db.prepare("INSERT INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?) ON CONFLICT(chat_id,application_id) DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP").bind(chat,key,json.dumps(data,ensure_ascii=False,separators=(",",":"))).run()
