"""Per-widget brand configuration for HelpCrunch.

Use the actual HelpCrunch applicationId -> brand mapping from a trusted API response.
Never guess a brand from the visitor's message.
"""
import json

BRAND_BY_DOMAIN = {
    "auctionauto.com.ua": "Auction Auto",
    "auctionauto.az": "Auction Auto",
    "atlanticauto.com.ua": "Atlantic Auto",
    "atlanticwest.com.ua": "Atlantic West",
    "atlanticexpress.com.ua": "Atlantic Express",
    "atlanticexpress.kh.ua": "Atlantic Express",
    "atlanticexpress.dp.ua": "Atlantic Express",
    "atlanticexpress.kiev.ua": "Atlantic Express",
    "autocanada.in.ua": "AutoCanada",
    "id4.com.ua": "ID4",
    "id6.com.ua": "ID6",
}

def configured_brands(mapping_json: str) -> dict:
    """Parse a trusted mapping like {'123':'Auction Auto', '456':'Atlantic Auto'}."""
    if not mapping_json:
        return {}
    obj = json.loads(mapping_json)
    if not isinstance(obj, dict):
        raise ValueError("Brand mapping must be an object")
    result = {}
    for key, value in obj.items():
        if not str(key).isdigit() or not isinstance(value, str) or not value.strip():
            raise ValueError("Invalid application ID or brand name")
        result[int(key)] = value.strip()
    return result

def brand_for_application(application_id, mapping: dict) -> str | None:
    try:
        return mapping.get(int(application_id))
    except (TypeError, ValueError):
        return None

def brand_instruction(brand: str | None) -> str:
    if not brand:
        return (
            "Ти ведеш первинні звернення автомобільної компанії. "
            "Назва бренду для цього віджета не налаштована; не називай конкретну компанію "
            "і не приписуй їй чужі тарифи. За потреби передай питання менеджеру."
        )
    return (
        f"Ти ведеш первинні консультації клієнтів бренду {brand}. "
        f"Представляйся тільки як {brand}. "
        "Не називай інші бренди групи як свою компанію. "
        "Правила продажів, логістичні умови та перевірений прайс є спільними для всіх "
        "сайтів цієї компанії. Користуйся одним перевіреним прайсом незалежно від бренду. "
        "Не вигадуй знижок чи додаткових умов, яких немає у спільних правилах."
    )
