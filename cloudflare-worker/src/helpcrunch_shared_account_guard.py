"""Detect manual operator messages even when human and AI share agent ID 21.

The only trustworthy distinction is an outbound message ID confirmed by
HelpCrunch. Unknown/malformed responses fail closed. Read-only helper.
"""
def human_takeover_since(messages_response, bot_message_ids, *, since_timestamp):
    if not isinstance(messages_response, dict) or not isinstance(messages_response.get("data"), list):
        return True
    if not isinstance(bot_message_ids, (list, tuple, set)) or not isinstance(since_timestamp, int):
        return True
    try:
        bots = {int(x) for x in bot_message_ids}
        if any(x <= 0 for x in bots):
            return True
    except (ValueError, TypeError):
        return True
    items = messages_response["data"]
    if not items:
        return True
    for item in items:
        if not isinstance(item, dict):
            return True
        try:
            created = int(item["createdAt"])
            msg_id = int(item["id"])
        except (KeyError, ValueError, TypeError):
            return True
        if created < since_timestamp:
            continue
        if item.get("type") == "tech":
            continue
        sender = item.get("from")
        if sender == "customer":
            continue
        if sender != "agent" or msg_id <= 0:
            return True
        if msg_id not in bots:
            return True
    return False
