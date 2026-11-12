"""Read-only night safety orchestration; never generates or sends replies.

Always fail closed for unknown brand, missing memory, missing HelpCrunch
message history or any unexplained operator activity.
"""
from helpcrunch_night_gate import night_preview_decision
from helpcrunch_night_history import load_night_history
from helpcrunch_bot_message_ids import load_bot_message_ids
from helpcrunch_shared_account_guard import human_takeover_since

async def evaluate_night_chat(metadata, enabled, brand, db, messages_response,
                              *, shift_started, now=None):
    decision = night_preview_decision(metadata, enabled, brand, now=now)
    if not decision["eligible"]:
        return decision
    if db is None or type(shift_started) is not int or shift_started <= 0:
        return {"eligible": False, "reason": "missing-state-or-shift"}
    chat, app = int(metadata["chat_id"]), int(metadata["application_id"])
    try:
        history = await load_night_history(db, chat, app)
        own_ids = await load_bot_message_ids(db, chat, app)
        if human_takeover_since(messages_response, own_ids, since_timestamp=shift_started):
            return {"eligible": False, "reason": "manual-takeover-or-unknown-history"}
    except (ValueError, TypeError, KeyError):
        return {"eligible": False, "reason": "untrusted-chat-state"}
    return {"eligible": True, "reason": "read-only-ready",
            "brand": brand, "history_turns": len(history)}
