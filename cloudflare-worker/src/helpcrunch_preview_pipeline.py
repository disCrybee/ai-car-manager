"""Optional D1-backed preview. Does not send messages to customers."""
from helpcrunch_planner import plan_incoming
from helpcrunch_store import load_dialog, commit_dialog_event


async def process_preview(raw, metadata, db=None, now=None):
    if not metadata["would_process"]:
        return {"status": "ignored"}
    if db is None:
        plan = plan_incoming(raw, now=now)
        return {"status": "preview", "clarification_needed": bool(plan["suggested_reply"])}
    chat = int(metadata["chat_id"])
    app = int(metadata["application_id"])
    message = int(metadata["message_id"])
    if chat <= 0 or app <= 0 or message <= 0:
        return {"status": "ignored"}
    existing = await load_dialog(db, chat, app)
    plan = plan_incoming(raw, state=existing, now=now)
    committed = await commit_dialog_event(db, f"{app}:{chat}:{message}", chat, app, plan["state"])
    if not committed:
        return {"status": "duplicate"}
    return {"status": "stored", "clarification_needed": bool(plan["suggested_reply"])}
