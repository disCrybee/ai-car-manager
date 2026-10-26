"""HelpCrunch-only Groq preparation. Not wired to outbound messaging.

Keep the previous prototype's company-specific pricing prompt out of HelpCrunch.
"""
import json
from helpcrunch_conversation import helpcrunch_system_prompt

PRIMARY = "openai/gpt-oss-120b"
FALLBACK = "openai/gpt-oss-20b"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def build_messages(brand, history, *, clarification=None):
    if len(history) > 16:
        history = history[-16:]
    result = [{"role": "system", "content": helpcrunch_system_prompt(brand)}]
    for item in history:
        if not isinstance(item, dict):
            raise ValueError("Invalid dialogue turn")
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("Unsupported dialogue role or text")
        if len(content) > 4000:
            raise ValueError("Dialogue turn too long")
        if content.strip():
            result.append({"role": role, "content": content.strip()})
    if clarification:
        result.append({"role": "system", "content":
                       "У наступній відповіді постав лише це уточнення, не здогадуйся значення: "
                       + clarification})
    return result


async def generate_reply(api_key, brand, history, *, clarification=None, transport=None):
    """Explicit caller invocation only; never sends text to HelpCrunch."""
    if not api_key:
        raise ValueError("Groq API key required")
    messages = build_messages(brand, history, clarification=clarification)
    if transport is None:
        from workers import fetch
        transport = fetch
    payload = {
        "model": PRIMARY, "messages": messages,
        "temperature": 0.2, "max_completion_tokens": 350,
        "stream": False,
    }
    response = await transport(
        ENDPOINT, method="POST",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        body=json.dumps(payload, ensure_ascii=False),
    )
    if response.status != 200:
        raise RuntimeError("Groq request failed")
    data = json.loads(await response.text())
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Groq returned an empty reply")
    return answer.strip()
