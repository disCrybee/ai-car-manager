"""Optional D1-backed preview. Does not send messages to customers."""
from helpcrunch_planner import plan_incoming
from helpcrunch_store import load_dialog, save_dialog, claim_event


async def process_preview(raw, metadata, db=None):
    if not metadata["would_process"]:
        return {"status": "ignored"}
    if db is None:
        plan = plan_incoming(raw)
        return {"status": "preview", "clarification_needed": bool(plan["suggested_reply"])}
    chat = int(metadata["chat_id"])
    app = int(metadata["application_id"])
    message = int(metadata["message_id"])
    if chat <= 0 or app <= 0 or message <= 0:
        return {"status": "ignored"}
    existing = await load_dialog(db, chat, app)
    plan = plan_incoming(raw, state=existing)
    # Preview requires idempotence before changing state.
    claimed = await claim_event(db, f"{app}:{chat}:{message}", chat, app)
    if not claimed:
        return {"status": "duplicate"}
    await save_dialog(db, chat, app, plan["state"])
    return {"status": "stored", "clarification_needed": bool(plan["suggested_reply"])}
