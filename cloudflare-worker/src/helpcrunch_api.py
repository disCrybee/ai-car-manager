"""HelpCrunch API adapter. No automatic customer-facing sends.

All write operations require explicit opt-in and exact test chat/agent IDs.
"""
import json

API_BASE = "https://api.helpcrunch.com/v1"


async def _request(api_key: str, method: str, path: str, payload=None):
    if not api_key:
        raise ValueError("HelpCrunch API key missing")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    options = {"method": method, "headers": headers}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        options["body"] = json.dumps(payload, ensure_ascii=False)
    from workers import fetch
    response = await fetch(API_BASE + path, **options)
    body = await response.text()
    if response.status < 200 or response.status >= 300:
        # Avoid logging response bodies: they can include private chat details.
        raise RuntimeError(f"HelpCrunch {method} {path.split('?')[0]} HTTP {response.status}")
    return json.loads(body)


async def list_agents(api_key: str):
    return await _request(api_key, "GET", "/agents?limit=100")


def manager_candidates(response: dict) -> list:
    """Return matching agent names and IDs, never emails."""
    agents = response.get("data", [])
    if not isinstance(agents, list):
        raise ValueError("Invalid agents response")
    names = ("андрій", "андрей", "andrii", "andriy", "andrey", "andrew")
    result = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        number = item.get("id")
        if isinstance(name, str) and any(x in name.casefold() for x in names):
            if isinstance(number, int) and number > 0:
                result.append({"id": number, "name": name})
    return result


async def list_applications(api_key: str):
    return await _request(api_key, "GET", "/applications?limit=100")


async def get_chat_messages(api_key: str, chat_id: int, *, limit: int = 20):
    if int(chat_id) <= 0:
        raise ValueError("Invalid chat id")
    if not 1 <= limit <= 100:
        raise ValueError("Invalid HelpCrunch message history limit")
    return await _request(api_key, "GET", f"/chats/{int(chat_id)}/messages?limit={limit}")


def test_message_payload(chat_id: int, agent_id: int, text: str,
                         *, allowed_chat_id: int, allowed_agent_id: int,
                         enabled: bool = False) -> dict:
    """Fail closed unless a separately authorized exact test chat is selected."""
    if not enabled:
        raise PermissionError("HelpCrunch outbound replies are disabled")
    if (int(chat_id) <= 0 or int(agent_id) <= 0
            or int(chat_id) != int(allowed_chat_id)
            or int(agent_id) != int(allowed_agent_id)):
        raise PermissionError("Only explicitly allowed test chat and agent may be used")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty reply")
    return {"chat": int(chat_id), "agent": int(agent_id),
            "text": text.strip(), "type": "message"}


async def send_test_message(api_key: str, chat_id: int, agent_id: int,
                            text: str, *, allowed_chat_id: int,
                            allowed_agent_id: int, enabled: bool = False):
    payload = test_message_payload(
        chat_id, agent_id, text, allowed_chat_id=allowed_chat_id,
        allowed_agent_id=allowed_agent_id, enabled=enabled,
    )
    return await _request(api_key, "POST", "/messages", payload)
