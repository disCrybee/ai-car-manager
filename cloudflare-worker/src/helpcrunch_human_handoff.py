"""Conservative human-agent handoff detection for future night rollout.

Use recent HelpCrunch messages. Unknown shapes fail closed. No outbound side effects.
"""
def human_operator_present(messages_response, automated_agent_id=21):
    if not isinstance(messages_response, dict) or not isinstance(messages_response.get("data"), list):
        return True
    messages = messages_response["data"]
    if not messages:
        return True
    for message in messages:
        if not isinstance(message, dict):
            return True
        if message.get("from") != "agent":
            continue
        if message.get("type") == "tech":
            continue
        agent = message.get("agent")
        if not isinstance(agent, dict):
            return True
        try:
            sender = int(agent.get("id"))
        except (ValueError, TypeError):
            return True
        if sender != automated_agent_id:
            return True
    return False
