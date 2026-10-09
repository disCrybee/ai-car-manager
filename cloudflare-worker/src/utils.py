import json
import re


def normalize(value) -> str:
    return " ".join(str(value or "").split()).strip()


def detect_language(text: str, fallback: str = "uk") -> str:
    low = normalize(text).lower()

    ru_markers = (
        "какой", "какая", "какие", "сколько", "пробег", "полный привод",
        "двигатель", "комплектация", "интересует", "стоимость", "хочу",
        "под ключ", "год", "года", "спасибо", "понятно",
    )
    uk_markers = (
        "який", "яка", "які", "скільки", "пробіг", "повний привід",
        "двигун", "комплектація", "цікавить", "вартість", "хочу",
        "під ключ", "рік", "року", "дякую", "зрозуміло",
    )

    ru = sum(marker in low for marker in ru_markers)
    uk = sum(marker in low for marker in uk_markers)

    if ru > uk:
        return "ru"
    if uk > ru:
        return "uk"
    return fallback or "uk"


def is_affirmative(text: str) -> bool:
    low = normalize(text).lower().strip(" .,!🙂👍✅")
    values = {
        "так", "да", "ага", "угу", "ок", "окей", "добре", "хорошо",
        "давайте", "давай", "так давайте", "да давайте", "хочу",
        "цікаво", "интересно", "підбирайте", "подбирайте", "покажіть",
        "покажите", "звісно", "конечно", "yes", "sure",
        "так підібрати", "да подобрать",
    }
    return low in values


def is_negative(text: str) -> bool:
    low = normalize(text).lower().strip(" .,!🙂❌")
    return low in {
        "ні", "нет", "не треба", "не нужно", "поки ні", "пока нет",
        "не цікаво", "не интересно", "ні дякую", "нет спасибо",
        "не хочу", "відмовляюсь", "отказываюсь",
    }


def is_simple_ack(text: str) -> bool:
    low = normalize(text).lower().strip(" .,!🙂👍")
    return low in {
        "зрозуміло", "ясно", "ок", "окей", "добре", "гаразд",
        "дякую", "спасибі", "понял", "понятно", "хорошо", "спасибо",
    }


def looks_like_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", normalize(text))
    return 10 <= len(digits) <= 15


def clean_phone(text: str) -> str:
    raw = normalize(text)
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return "+" + digits
    return digits


def strip_citations(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"【[^】]*】", "", value)
    value = re.sub(r"\[\d+\s*†\s*L\d+(?:\s*-\s*L?\d+)?\]", "", value)
    value = re.sub(r"\(\s*\d+\s*†\s*L\d+(?:\s*-\s*L?\d+)?\s*\)", "", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def parse_json_object(text: str):
    raw = normalize(text)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", str(text or ""), flags=re.DOTALL)
    if not match:
        return {}

    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
