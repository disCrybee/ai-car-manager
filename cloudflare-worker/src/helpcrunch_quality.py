"""Privacy-minimized quality signals; isolated from live conversation behavior."""
import json
import re

ANALYTICS_OFFSET = 4000000000

def signals(text, answer):
    customer = text.casefold()
    reply = answer.casefold()
    no_budget = any(p in customer for p in ("не знаю", "не визначив", "просто цікавить вартість", "запропонуйте", "поки без бюджету", "хочу зрозуміти ціни"))
    budget_repeat = no_budget and any(p in reply for p in ("який бюджет", "яка сума бюджету", "на який бюджет", "яку суму плануєте"))
    phone_request = any(p in reply for p in ("номер телефону", "ваш номер", "залиште номер"))
    mileage_question = "пробіг" in reply and "?" in reply
    return {"budget_declined": int(no_budget), "budget_repeated": int(budget_repeat),
            "phone_requested": int(phone_request), "mileage_asked": int(mileage_question)}

async def record_quality(db, chat_id, application_id, message_id, incoming, answer):
    """No raw messages, contact data, chat ID or phone stored in analytics JSON."""
    chat, app, msg = int(chat_id), int(application_id), int(message_id)
    if min(chat,app,msg) <= 0 or app >= 1000000000:
        raise ValueError("Invalid analytics identifiers")
    key = -(ANALYTICS_OFFSET + app)
    data = signals(incoming, answer)
    payload = json.dumps(data, separators=(",", ":"))
    # Insert-only and idempotent by message id; one row per event.
    await db.prepare(
        "INSERT OR IGNORE INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?)"
    ).bind(msg, key, payload).run()

async def quality_summary(db):
    rows = await db.prepare(
        "SELECT state_json FROM hc_dialog_state WHERE application_id <= ? ORDER BY updated_at DESC LIMIT 500"
    ).bind(-ANALYTICS_OFFSET).all()
    data = rows.get("results", []) if isinstance(rows,dict) else getattr(rows,"results",[])
    totals = {k:0 for k in ("budget_declined","budget_repeated","phone_requested","mileage_asked")}
    valid = 0
    for row in data:
        try:
            item = json.loads(row.get("state_json") if isinstance(row,dict) else row.state_json)
            if any(type(item.get(k)) is not int or item[k] not in (0,1) for k in totals):
                continue
            valid += 1
            for k in totals: totals[k] += item[k]
        except (ValueError, TypeError, AttributeError):
            continue
    recommendations = []
    if totals["budget_repeated"]:
        recommendations.append("Перевірити сценарії, де бюджет повторно запитують після відмови клієнта.")
    if totals["phone_requested"] and not totals["mileage_asked"]:
        recommendations.append("Перевірити, чи не запитується телефон до уточнення пробігу.")
    return {"analyzed_replies":valid,"signals":totals,"recommendations":recommendations,
            "scope":"last 500 recorded replies","automatic_policy_changes":False}
