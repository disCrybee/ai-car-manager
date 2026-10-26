"""Single night webhook pipeline; live delivery is separately gated and OFF by default.

This is intentionally not invoked by the production/main Worker. The staging
Worker may invoke it for read-only evaluation with no automatic sends.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from helpcrunch_api import get_chat_messages, _request
from helpcrunch_bot_message_ids import record_bot_message_id
from helpcrunch_night_history import load_night_history, save_night_history
from helpcrunch_night_review import evaluate_night_chat
from helpcrunch_shipping_lookup import confirmed_route_reply, shipping_context
from helpcrunch_budget_guard import fresh_consultation, low_usd_budget_reply
from helpcrunch_groq import generate_reply
from helpcrunch_pilot_completion import contains_phone, ACK, is_substantive_followup
from helpcrunch_night_completion import get_night_completion, set_night_completion
from helpcrunch_store import claim_event
from helpcrunch_webhook import is_night

KYIV = ZoneInfo("Europe/Kyiv")
AGENT_ID = 21

def shift_start_timestamp(now=None):
    local = (now or datetime.now(KYIV)).astimezone(KYIV)
    shift_day = local.date() if local.hour >= 23 else (local - timedelta(days=1)).date()
    return int(datetime(shift_day.year, shift_day.month, shift_day.day, 23, tzinfo=KYIV).timestamp())

def extract_created_id(response):
    if not isinstance(response, dict):
        raise ValueError("Missing HelpCrunch send receipt")
    item = response.get("data", response)
    if not isinstance(item, dict):
        raise ValueError("Invalid HelpCrunch send receipt")
    value = item.get("id")
    if type(value) is not int or value <= 0:
        raise ValueError("Missing confirmed message ID")
    return value

async def process_night_event(metadata, incoming, *, env, brand, now=None,
                              live=False, history_response=None):
    """Run full safety gate; only send when caller AND environment opt in.

    Live flag is never passed by current staging entrypoint. A future
    activation must be reviewed separately after shadow-mode validation.
    """
    enabled = str(getattr(env, "HELPCRUNCH_NIGHT_ENABLED", "") or "")
    now = now or datetime.now(KYIV)
    if enabled != "true" or not is_night(now):
        return {"mode": "night-off"}
    if not isinstance(incoming, str) or not 1 <= len(incoming.strip()) <= 1000:
        return {"mode": "night-invalid-content"}
    db = getattr(env, "HC_DB", None)
    api_key = str(getattr(env, "HELPCRUNCH_API_KEY", "") or "")
    groq_key = str(getattr(env, "GROQ_API_KEY", "") or "")
    if db is None or not api_key:
        return {"mode": "night-not-configured"}
    chat, app, msg = (int(metadata[k]) for k in ("chat_id", "application_id", "message_id"))
    if history_response is None:
        # 100 is the documented maximum; do not silently trust 20 recent messages.
        history_response = await get_chat_messages(api_key, chat, limit=100)
    brand = None
    review = await evaluate_night_chat(metadata, enabled, brand, db, history_response,
                                       shift_started=shift_start_timestamp(now), now=now)
    if not review["eligible"]:
        return {"mode": "night-blocked", "reason": review["reason"]}
    if not live or str(getattr(env, "HELPCRUNCH_NIGHT_SEND_ENABLED", "") or "") != "true":
        return {"mode": "night-shadow-ready", "brand": brand, "chat_id": chat}
    if not groq_key:
        return {"mode": "night-not-configured"}
    # A claimed event is never retried after uncertain third-party send.
    if not await claim_event(db, f"night:{app}:{chat}:{msg}", chat, app):
        return {"mode": "night-duplicate"}
    completed = await get_night_completion(db, chat, app)
    restarting = fresh_consultation(incoming)
    if completed and not restarting and not is_substantive_followup(incoming):
        return {"mode": "night-completed-silent"}
    old = await load_night_history(db, chat, app)
    turns = ([] if restarting else old) + [
        {"role": "user", "content": incoming}]
    if contains_phone(incoming):
        answer = ACK
    else:
        answer = (low_usd_budget_reply(incoming) if fresh_consultation(incoming) else None)
        if answer is None:
            answer = confirmed_route_reply(turns)
        if answer is None:
            answer = await generate_reply(groq_key, brand, turns,
                                          company_context=shipping_context(turns))
    if not is_night():
        return {"mode": "night-cutoff"}
    # Re-read to catch a manager reply while Groq was generating.
    current_messages = await get_chat_messages(api_key, chat, limit=100)
    second = await evaluate_night_chat(metadata, enabled, brand, db, current_messages,
                                       shift_started=shift_start_timestamp(), now=datetime.now(KYIV))
    if not second["eligible"]:
        return {"mode":"night-blocked-before-send", "reason":second["reason"]}
    sent = await _request(api_key, "POST", "/messages",
                          {"chat":chat, "agent":AGENT_ID, "text":answer, "type":"message"})
    receipt = extract_created_id(sent)
    await record_bot_message_id(db, chat, app, receipt)
    await save_night_history(db, chat, app, turns + [{"role":"assistant","content":answer}])
    if contains_phone(incoming) or restarting:
        await set_night_completion(db, chat, app, contains_phone(incoming))
    return {"mode":"night-replied", "chat_id":chat}
