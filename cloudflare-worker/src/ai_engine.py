import json

from workers import fetch

from config import (
    EXTRACTOR_PROMPT,
    FALLBACK_MODEL,
    GROQ_URL,
    PRIMARY_MODEL,
    SYSTEM_PROMPT,
)
from state_store import trim_history
from utils import normalize, parse_json_object, strip_citations
from vehicle_logic import is_factual_vehicle_question, normalize_memory, vehicle_label


def _memory_context(memory: dict) -> str:
    data = normalize_memory(memory)

    fields = []
    for key, label in (
        ("brand", "Марка"),
        ("model", "Модель"),
        ("year", "Рік"),
        ("mileage", "Пробіг"),
        ("trim", "Комплектація"),
        ("budget", "Бюджет"),
        ("engine", "Двигун"),
        ("drive", "Привід"),
        ("battery", "Батарея"),
        ("color", "Колір"),
    ):
        value = data.get(key)
        if value:
            fields.append(f"{label}: {value}")

    if not fields:
        return "Контекст авто ще не визначений."

    return (
        "ПОТОЧНИЙ КОНТЕКСТ АВТО. Не підмінюй його іншою моделлю/роком: "
        + "; ".join(fields)
        + "."
    )


async def _groq(
    api_key: str,
    model: str,
    messages: list,
    *,
    browser: bool = False,
    max_tokens: int = 360,
    temperature: float = 0.12,
):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": "low",
        "stream": False,
        "citation_options": "disabled",
    }

    if browser:
        payload["tools"] = [{"type": "browser_search"}]
        payload["tool_choice"] = "required"

    response = await fetch(
        GROQ_URL,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body=json.dumps(payload, ensure_ascii=False),
    )

    body = await response.text()

    if response.status != 200:
        raise RuntimeError(
            f"Groq {model} HTTP {response.status}: {body[:500]}"
        )

    data = json.loads(body)

    answer = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )

    if not answer:
        raise RuntimeError("Groq returned empty answer")

    return strip_citations(answer)


async def extract_slots(
    api_key: str,
    memory: dict,
    user_text: str,
):
    messages = [
        {
            "role": "system",
            "content": EXTRACTOR_PROMPT,
        },
        {
            "role": "system",
            "content": (
                "Вже відомо з попередніх повідомлень (не копіюй це в результат, "
                "якщо клієнт не повторив у поточному повідомленні): "
                + _memory_context(memory)
            ),
        },
        {
            "role": "user",
            "content": user_text,
        },
    ]

    try:
        answer = await _groq(
            api_key,
            FALLBACK_MODEL,
            messages,
            browser=False,
            max_tokens=220,
            temperature=0.0,
        )
        return parse_json_object(answer)
    except Exception as error:
        print("SLOT EXTRACTOR ERROR:", str(error))
        return {}


async def consult(
    api_key: str,
    history: list,
    memory: dict,
    user_text: str,
):
    browser_required = is_factual_vehicle_question(user_text)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "system",
            "content": _memory_context(memory),
        },
        *trim_history(history),
        {
            "role": "user",
            "content": user_text,
        },
    ]

    errors = []

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            return await _groq(
                api_key,
                model,
                messages,
                browser=browser_required,
                max_tokens=520,
                temperature=0.12,
            )
        except Exception as error:
            errors.append(str(error))
            print(f"CONSULT {model} ERROR:", str(error))

    # For factual specs we prefer no answer over a hallucinated answer.
    if browser_required:
        raise RuntimeError(
            "Technical web verification unavailable: " + " | ".join(errors[-2:])
        )

    # Subjective/general advice may fall back to model knowledge.
    return await _groq(
        api_key,
        FALLBACK_MODEL,
        messages,
        browser=False,
        max_tokens=420,
        temperature=0.18,
    )


async def classify_body_type(
    api_key: str,
    memory: dict,
):
    vehicle = vehicle_label(memory)
    if not vehicle:
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "Classify the vehicle into exactly one token: "
                "SMALL, SUV, LARGE, MOTO. "
                "SMALL=sedan/coupe/hatch/wagon; "
                "SUV=crossover/SUV/standard pickup; "
                "LARGE=dually/extra-large/over 20 ft; "
                "MOTO=motorcycle. Return only the token."
            ),
        },
        {
            "role": "user",
            "content": vehicle,
        },
    ]

    try:
        answer = normalize(
            await _groq(
                api_key,
                FALLBACK_MODEL,
                messages,
                browser=False,
                max_tokens=20,
                temperature=0.0,
            )
        ).upper()
    except Exception:
        return None

    mapping = {
        "SMALL": "Small vehicle/Coupe/Sedan",
        "SUV": "Crossover/SUV/Standard Truck",
        "LARGE": "Extra Large Vehicle/Dually/Over 20 ft.",
        "MOTO": "Motorcycle",
    }

    for token, category in mapping.items():
        if token in answer:
            return category

    return None
