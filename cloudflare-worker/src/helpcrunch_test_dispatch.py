"""Fail-closed staging webhook eligibility and send-once reservation.

One exact customer chat; opt-in is disabled unless literal 'true'. Claim
the event before any non-idempotent send to prevent webhook retry duplicates.
"""
from helpcrunch_store import claim_event

TEST_CHAT_ID = 60354
TEST_AGENT_ID = 21

def enabled_for_event(metadata, flag):
    try:
        chat = int(metadata.get("chat_id") or 0)
        msg = int(metadata.get("message_id") or 0)
        app = int(metadata.get("application_id") or 0)
    except (ValueError, TypeError):
        return False
    return (flag == "true" and metadata.get("event") == "message.chat.customer"
            and chat == TEST_CHAT_ID and msg > 0 and app > 0)


async def reserve_test_reply(db, metadata):
    if db is None:
        raise RuntimeError("D1 is required for once-only test dispatch")
    app = int(metadata["application_id"])
    msg = int(metadata["message_id"])
    return await claim_event(db, f"auto60354:{app}:{msg}", TEST_CHAT_ID, app)
