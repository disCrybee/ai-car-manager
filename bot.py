import asyncio
import json
import os
import re
import time
from pathlib import Path
from difflib import SequenceMatcher

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.enums import ChatAction
from dotenv import load_dotenv

from price_lookup import (
    PRICE_DATA,
    get_best_usa_route,
    get_vehicle_rates,
)


# ==========================================
# ШЛЯХИ
# ==========================================

BASE_DIR = Path(__file__).resolve().parent

SYSTEM_PROMPT_FILE = BASE_DIR / "prompts" / "system_prompt.txt"
COMPANY_INFO_FILE = BASE_DIR / "prompts" / "company_info.txt"
DIALOG_MEMORY_FILE = BASE_DIR / "data" / "dialog_memory.json"


def load_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Не знайдено файл:\n{path}"
        )

    return path.read_text(
        encoding="utf-8"
    ).strip()


# ==========================================
# НАЛАШТУВАННЯ
# ==========================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN:
    raise ValueError(
        "Не знайдено BOT_TOKEN у файлі .env"
    )

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Щоб не витрачати credits на один і той самий запит.
WEB_CACHE_TTL_SECONDS = 60 * 60 * 24
web_search_cache = {}

SYSTEM_PROMPT = load_text_file(
    SYSTEM_PROMPT_FILE
)

COMPANY_INFO = load_text_file(
    COMPANY_INFO_FILE
)


# ==========================================
# PROMPT ДЛЯ КАРТКИ ЛІДА
# ==========================================

SUMMARY_PROMPT = """
Ти формуєш дуже коротку картку ліда
для менеджера автомобільної компанії.

На основі діалогу витягни ТІЛЬКИ те,
що клієнт реально повідомив.

Нічого не вигадуй і не доповнюй від себе.

Формат:

Авто: ...
Модель: ...
Рік: ...
Бюджет: ...
Пробіг: ...
Комплектація: ...
Двигун / батарея / привід: ...
Побажання: ...

"Авто" — це марка/бренд, наприклад Lincoln, BMW, Toyota.
"Модель" — конкретна модель, наприклад Corsair, X5, Camry.

Якщо параметр не вказаний —
напиши "не вказано".

Не додавай історію діалогу.
Не цитуй повідомлення.
Не пиши вступ або висновок.
"""


# ==========================================
# ПАМ'ЯТЬ ДІАЛОГУ
# ==========================================

def default_dialog_memory():
    return {
        "client_statements": [],
        "vehicle_request": [],

        # Окремі слоти поточного запиту.
        # Це важливо: Mercedes-Benz -> S-Class -> 2016-2017
        # більше не повинно губитися серед звичайного тексту.
        "brand": [],
        "model": [],

        "years": [],
        "budget": [],
        "mileage": [],
        "engine": [],
        "drive": [],
        "battery": [],
        "trim": [],
        "color": [],
        "preferences": [],

        # Що бот уже питав.
        "asked_questions": [],

        # Тема ОСТАННЬОГО питання бота.
        # Завдяки цьому коротка відповідь "S-class"
        # розуміється саме як модель, а "2016-2017" — як роки.
        "last_question_topic": None,
    }


def load_persistent_dialog_data():
    if not DIALOG_MEMORY_FILE.exists():
        return {}, {}

    try:
        raw = json.loads(
            DIALOG_MEMORY_FILE.read_text(
                encoding="utf-8"
            )
        )

        histories_raw = raw.get(
            "histories",
            {}
        )

        memories_raw = raw.get(
            "memories",
            {}
        )

        histories = {
            int(user_id): value
            for user_id, value
            in histories_raw.items()
        }

        memories = {
            int(user_id): value
            for user_id, value
            in memories_raw.items()
        }

        return histories, memories

    except Exception as error:
        print(
            "Не вдалося завантажити "
            f"пам'ять діалогів: {error}"
        )

        return {}, {}


def save_persistent_dialog_data():
    try:
        DIALOG_MEMORY_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "histories": {
                str(user_id): history[-30:]
                for user_id, history
                in chat_histories.items()
            },
            "memories": {
                str(user_id): memory
                for user_id, memory
                in dialog_memories.items()
            },
        }

        DIALOG_MEMORY_FILE.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except Exception as error:
        print(
            "Не вдалося зберегти "
            f"пам'ять діалогів: {error}"
        )


chat_histories, dialog_memories = (
    load_persistent_dialog_data()
)

user_states = {}


def get_dialog_memory(
    user_id: int,
):
    defaults = default_dialog_memory()

    if user_id not in dialog_memories:
        dialog_memories[user_id] = (
            default_dialog_memory()
        )

    memory = dialog_memories[
        user_id
    ]

    # Старий dialog_memory.json може не мати
    # нових ключів brand/model/last_question_topic.
    # Додаємо їх автоматично без видалення старої пам'яті.
    for key, default_value in defaults.items():
        if key not in memory:
            if isinstance(
                default_value,
                list,
            ):
                memory[key] = []
            else:
                memory[key] = default_value

    return memory


def add_unique_memory(
    memory: dict,
    key: str,
    value: str,
    limit: int = 8,
):
    value = str(value).strip()

    if not value:
        return

    values = memory.setdefault(
        key,
        []
    )

    if value not in values:
        values.append(
            value
        )

    if len(values) > limit:
        memory[key] = values[
            -limit:
        ]



# ==========================================
# РОЗУМНА ПАМ'ЯТЬ ПОТОЧНОГО ЗАПИТУ
# ==========================================

BRAND_ALIASES = {
    "mercedes benz": "Mercedes-Benz",
    "mercedes-benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "мерседес": "Mercedes-Benz",

    "bmw": "BMW",
    "бмв": "BMW",

    "audi": "Audi",
    "ауди": "Audi",

    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "фольксваген": "Volkswagen",

    "toyota": "Toyota",
    "тойота": "Toyota",

    "lexus": "Lexus",
    "лексус": "Lexus",

    "ford": "Ford",
    "форд": "Ford",

    "chevrolet": "Chevrolet",
    "шевроле": "Chevrolet",

    "jeep": "Jeep",
    "джип": "Jeep",

    "nissan": "Nissan",
    "ниссан": "Nissan",
    "ніссан": "Nissan",

    "kia": "Kia",
    "киа": "Kia",
    "кіа": "Kia",

    "hyundai": "Hyundai",
    "хюндай": "Hyundai",
    "хендай": "Hyundai",

    "mazda": "Mazda",
    "мазда": "Mazda",

    "honda": "Honda",
    "хонда": "Honda",

    "subaru": "Subaru",
    "субару": "Subaru",

    "tesla": "Tesla",
    "тесла": "Tesla",

    "porsche": "Porsche",
    "порше": "Porsche",

    "volvo": "Volvo",
    "вольво": "Volvo",

    "cadillac": "Cadillac",
    "кадиллак": "Cadillac",

    "dodge": "Dodge",
    "додж": "Dodge",

    "land rover": "Land Rover",
    "range rover": "Range Rover",

    "jaguar": "Jaguar",
    "ягуар": "Jaguar",

    "infiniti": "Infiniti",
    "инфинити": "Infiniti",

    "rivian": "Rivian",
    "ривиан": "Rivian",
    "рівіан": "Rivian",

    "polestar": "Polestar",
    "полестар": "Polestar",

    "fisker": "Fisker",
    "фискер": "Fisker",
    "фіскер": "Fisker",
}


def detect_brand_name(
    text: str,
):
    low = text.lower()

    for alias in sorted(
        BRAND_ALIASES.keys(),
        key=len,
        reverse=True,
    ):
        if alias in low:
            return BRAND_ALIASES[
                alias
            ]

    return None


def detect_question_topics(
    answer: str,
):
    """
    Повертає ВСІ теми, які бот запитує.

    Це важливо для фраз типу:
    "Які параметри важливі: рік, бюджет, пробіг чи комплектація?"
    Тут одразу 4 теми.
    """

    q = " ".join(
        answer.lower().split()
    )

    topics = set()

    # Модель
    if (
        "модел" in q
        or "model" in q
        or "який клас" in q
        or "якого класу" in q
        or "какой класс" in q
    ):
        topics.add("model")

    # Марка / бренд
    if any(
        x in q
        for x in [
            "марка",
            "бренд",
            "brand",
        ]
    ):
        topics.add("brand")

    # Рік
    if any(
        x in q
        for x in [
            "якого року",
            "який рік",
            "які роки",
            "року",
            "років",
            "рік",
            "какого года",
            "какой год",
            "какие годы",
            "года",
            "год",
        ]
    ):
        topics.add("year")

    # Бюджет
    if any(
        x in q
        for x in [
            "бюджет",
            "під ключ",
            "под ключ",
            "скільки плануєте",
            "сколько планируете",
        ]
    ):
        topics.add("budget")

    # Пробіг
    if any(
        x in q
        for x in [
            "пробіг",
            "пробег",
            "по пробігу",
            "по пробегу",
            "кілометр",
            "миль",
        ]
    ):
        topics.add("mileage")

    # Комплектація
    if any(
        x in q
        for x in [
            "комплектац",
            "максимал",
            "пред-топ",
            "предтоп",
            "опції",
            "опции",
        ]
    ):
        topics.add("trim")

    # Двигун
    if any(
        x in q
        for x in [
            "двигун",
            "двигатель",
            "мотор",
            "бензин",
            "дизел",
        ]
    ):
        topics.add("engine")

    # Привід
    if any(
        x in q
        for x in [
            "привід",
            "привод",
            "xdrive",
            "awd",
            "fwd",
            "rwd",
        ]
    ):
        topics.add("drive")

    # Батарея
    if any(
        x in q
        for x in [
            "батаре",
            "квт",
            "kwh",
        ]
    ):
        topics.add("battery")

    # Колір
    if any(
        x in q
        for x in [
            "колір",
            "цвет",
        ]
    ):
        topics.add("color")

    return topics


def detect_question_topic(
    answer: str,
):
    """
    Для контексту короткої відповіді потрібна одна,
    найімовірніша тема ОСТАННЬОГО питання.
    """

    questions = re.findall(
        r"[^?]*\?",
        answer,
        flags=re.DOTALL,
    )

    if not questions:
        return None

    topics = detect_question_topics(
        questions[-1]
    )

    # Пріоритет для типового qualification flow.
    priority = [
        "model",
        "brand",
        "year",
        "mileage",
        "trim",
        "engine",
        "drive",
        "battery",
        "color",
        "budget",
    ]

    for topic in priority:
        if topic in topics:
            return topic

    return None


def looks_like_short_slot_reply(
    text: str,
):
    clean = " ".join(
        text.split()
    ).strip()

    if not clean:
        return False

    if "?" in clean:
        return False

    # Відповідь на уточнення може бути досить довгою,
    # але це вже не має бути цілий новий запит.
    return len(clean) <= 100


def store_contextual_answer(
    memory: dict,
    topic: str | None,
    clean: str,
):
    """
    Зберігаємо коротку відповідь відповідно
    до попереднього питання бота.

    Приклад:
    бот: "Яка модель?"
    клієнт: "S-class"
    -> model = S-class
    """

    if not topic:
        return

    if not looks_like_short_slot_reply(
        clean
    ):
        return

    topic_to_key = {
        "model": "model",
        "brand": "brand",
        "budget": "budget",
        "mileage": "mileage",
        "trim": "trim",
        "engine": "engine",
        "drive": "drive",
        "battery": "battery",
        "color": "color",
    }

    key = topic_to_key.get(
        topic
    )

    if key:
        add_unique_memory(
            memory,
            key,
            clean,
            limit=5,
        )


def build_current_vehicle_summary(
    memory: dict,
):
    parts = []

    brands = memory.get(
        "brand",
        [],
    )

    models = memory.get(
        "model",
        [],
    )

    years = memory.get(
        "years",
        [],
    )

    if brands:
        parts.append(
            brands[-1]
        )

    if models:
        model = models[-1]

        if (
            not parts
            or model.lower()
            not in parts[-1].lower()
        ):
            parts.append(
                model
            )

    if years:
        if len(years) == 1:
            parts.append(
                years[-1]
            )

        else:
            parts.append(
                f"{years[-2]}-{years[-1]}"
            )

    return " ".join(
        parts
    ).strip()


def known_memory_topics(
    memory: dict,
):
    known = set()

    mapping = {
        "brand": "brand",
        "model": "model",
        "year": "years",
        "budget": "budget",
        "mileage": "mileage",
        "trim": "trim",
        "engine": "engine",
        "drive": "drive",
        "battery": "battery",
        "color": "color",
    }

    for topic, key in mapping.items():
        if memory.get(
            key,
            []
        ):
            known.add(
                topic
            )

    return known


def repeated_known_questions(
    answer: str,
    memory: dict,
):
    """
    Знаходить усі вже відомі параметри,
    які Qwen знову намагається запитати.
    """

    question_parts = re.findall(
        r"[^?]*\?",
        answer,
        flags=re.DOTALL,
    )

    known = known_memory_topics(
        memory
    )

    repeated = []

    for part in question_parts:
        topics = detect_question_topics(
            part
        )

        for topic in topics:
            if (
                topic in known
                and topic not in repeated
            ):
                repeated.append(
                    topic
                )

    return repeated


def build_memory_fallback(
    user_id: int,
    language: str,
):
    """
    Жорсткий Python fallback.

    Якщо Qwen починає перепитувати відоме,
    Python або:
    1. питає наступний невідомий параметр;
    2. або, якщо запит уже добре сформований,
       м'яко пропонує актуальну підбірку.
    """

    memory = get_dialog_memory(
        user_id
    )

    vehicle = build_current_vehicle_summary(
        memory
    )

    if not vehicle:
        vehicle = (
            "цей автомобіль"
            if language == "uk"
            else "этот автомобиль"
        )

    # Додаткові відомі параметри.
    details = []

    mileage = memory.get(
        "mileage",
        []
    )

    trim = memory.get(
        "trim",
        []
    )

    engine = memory.get(
        "engine",
        []
    )

    drive = memory.get(
        "drive",
        []
    )

    battery = memory.get(
        "battery",
        []
    )

    budget = memory.get(
        "budget",
        []
    )

    if mileage:
        details.append(
            mileage[-1]
        )

    if trim:
        details.append(
            trim[-1]
        )

    # Наскільки запит уже сформований.
    optional_known_count = sum(
        1
        for values in [
            mileage,
            trim,
            engine,
            drive,
            battery,
            budget,
        ]
        if values
    )

    core_ready = (
        bool(memory.get("brand"))
        and bool(memory.get("model"))
        and bool(memory.get("years"))
    )

    # Якщо вже є марка + модель + роки
    # і хоча б два додаткові побажання —
    # не продовжуємо анкету нескінченно.
    if (
        core_ready
        and optional_known_count >= 2
    ):
        extra = ""

        if details:
            extra = (
                ", "
                + ", ".join(
                    details
                )
            )

        if language == "ru":
            return (
                f"Хорошо, ориентируемся на {vehicle}{extra}. "
                "Кстати, если хотите, можем подобрать несколько "
                "актуальных вариантов под эти параметры и посмотреть, "
                "что сейчас есть на торгах. <OFFER_SELECTION>"
            )

        return (
            f"Добре, орієнтуємося на {vehicle}{extra}. "
            "До речі, якщо хочете, можемо підібрати кілька "
            "актуальних варіантів під ці параметри й подивитися, "
            "що зараз є на торгах. <OFFER_SELECTION>"
        )

    next_fields = [
        (
            "mileage",
            "По пробігу є побажання?",
            "По пробегу есть пожелания?",
        ),
        (
            "trim",
            "По комплектації є побажання?",
            "По комплектации есть пожелания?",
        ),
        (
            "engine",
            "По двигуну є побажання?",
            "По двигателю есть пожелания?",
        ),
        (
            "drive",
            "По приводу є побажання?",
            "По приводу есть пожелания?",
        ),
        (
            "budget",
            "По бюджету під ключ уже є орієнтир?",
            "По бюджету под ключ уже есть ориентир?",
        ),
    ]

    question = None

    for key, uk_q, ru_q in next_fields:
        if not memory.get(
            key,
            [],
        ):
            question = (
                uk_q
                if language == "uk"
                else ru_q
            )
            break

    if language == "ru":
        if question:
            return (
                f"Хорошо, ориентируемся на {vehicle}. "
                f"{question}"
            )

        return (
            f"Хорошо, ориентируемся на {vehicle}. "
            "Если хотите, можем посмотреть актуальные варианты "
            "на торгах. <OFFER_SELECTION>"
        )

    if question:
        return (
            f"Добре, орієнтуємося на {vehicle}. "
            f"{question}"
        )

    return (
        f"Добре, орієнтуємося на {vehicle}. "
        "Якщо хочете, можемо подивитися актуальні варіанти "
        "на торгах. <OFFER_SELECTION>"
    )



# ==========================================
# ДЕТЕРМІНОВАНИЙ QUALIFICATION FLOW
# ==========================================

def looks_like_year_only_reply(text: str):
    clean = text.lower().strip()
    return bool(
        re.fullmatch(
            r"(?:19[8-9]\d|20[0-3]\d)(?:\s*[-–—/]\s*(?:19[8-9]\d|20[0-3]\d))?(?:\s*(?:рік|року|роки|год|года|годы))?",
            clean,
        )
    )


def looks_like_mileage_reply(text: str):
    low = text.lower()
    return (
        any(x in low for x in ['км', 'миль', 'пробіг', 'пробег'])
        and bool(re.search(r'\d', low))
    )


def looks_like_budget_reply(text: str):
    low = text.lower()
    return any(
        x in low
        for x in [
            '$', 'usd', 'дол', 'бюджет',
            'під ключ', 'под ключ',
        ]
    ) and bool(re.search(r'\d', low))


def looks_like_consultation_question(text: str):
    """
    Якщо клієнт реально питає щось по авто — не перехоплюємо
    його детермінованою анкетою. Такі повідомлення йдуть у Qwen/web.
    """
    low = text.lower().strip()

    if '?' in text:
        return True

    question_starts = [
        'який ', 'яка ', 'яке ', 'які ',
        'скільки ', 'що ', 'чим ', 'чому ', 'коли ', 'де ',
        'какой ', 'какая ', 'какое ', 'какие ',
        'сколько ', 'что ', 'чем ', 'почему ', 'когда ', 'где ',
    ]

    if any(low.startswith(x) for x in question_starts):
        return True

    technical_request_words = [
        'характеристик', 'комплектац', 'двигун', 'двигатель',
        'коробк', 'батаре', 'запас хода', 'запас ходу',
        'надійн', 'надежн', 'ресурс', 'різниц', 'разниц',
        'відрізня', 'отлича', 'рестайл', 'поколін', 'поколен',
    ]

    # "BMW XM характеристики" — це консультаційний запит,
    # навіть якщо клієнт не поставив знак питання.
    if any(word in low for word in technical_request_words):
        return True

    return False


def clean_model_candidate(text: str, brand: str | None = None):
    clean = ' '.join(text.split()).strip(' ,.!?:;')

    if not clean or len(clean) > 50:
        return None

    if looks_like_year_only_reply(clean):
        return None

    if looks_like_mileage_reply(clean):
        return None

    if looks_like_budget_reply(clean):
        return None

    low = clean.lower()

    # Прибираємо службові слова клієнта.
    prefixes = [
        'цікавить ', 'интересует ', 'хочу ', 'шукаю ', 'ищу ',
        'автомобіль ', 'автомобиль ', 'машина ', 'модель ',
    ]

    for prefix in prefixes:
        if low.startswith(prefix):
            clean = clean[len(prefix):].strip()
            low = clean.lower()
            break

    if brand:
        # Прибираємо alias поточної марки з "BMW XM" -> "XM".
        for alias, canonical in sorted(
            BRAND_ALIASES.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if canonical != brand:
                continue

            pattern = re.compile(
                re.escape(alias),
                flags=re.IGNORECASE,
            )

            clean = pattern.sub(
                ' ',
                clean,
            )

        clean = ' '.join(clean.split()).strip(' ,.!?:;')

    if not clean:
        return None

    # Модель — короткий ідентифікатор, а не речення.
    if len(clean.split()) > 4:
        return None

    if not re.search(r'[A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9]', clean):
        return None

    return clean


def extract_model_from_message(text: str, memory: dict):
    """
    Головне виправлення для XM / X5 / S-Class / 540i тощо.
    Python сам фіксує модель, а не чекає, поки Qwen її "згадає".
    """
    clean = ' '.join(text.split()).strip()
    brand = (
        memory.get('brand', [])[-1]
        if memory.get('brand')
        else detect_brand_name(clean)
    )

    last_topic = memory.get('last_question_topic')

    # Якщо бот щойно питав модель — коротка відповідь і є моделлю.
    if last_topic == 'model' and '?' not in clean:
        return clean_model_candidate(clean, brand)

    detected_brand = detect_brand_name(clean)

    # "BMW XM" / "Mercedes S-Class"
    if detected_brand:
        candidate = clean_model_candidate(clean, detected_brand)
        if candidate and candidate.lower() != detected_brand.lower():
            return candidate

    # Якщо марка вже відома, але модель ще ні — коротке "XM" / "X5"
    # трактуємо як модель.
    if brand and not memory.get('model') and '?' not in clean:
        return clean_model_candidate(clean, brand)

    return None


def qualification_summary(memory: dict):
    return build_current_vehicle_summary(memory)


def qualification_soft_offer(language: str, memory: dict):
    vehicle = qualification_summary(memory)

    details = []
    if memory.get('mileage'):
        details.append(memory['mileage'][-1])
    if memory.get('trim'):
        details.append(memory['trim'][-1])

    suffix = ''
    if details:
        suffix = ', ' + ', '.join(details)

    if language == 'ru':
        return (
            f"Хорошо, ориентируемся на {vehicle}{suffix}. "
            "Если хотите, можем посмотреть несколько актуальных "
            "вариантов под эти параметры на торгах. Интересно?"
        )

    return (
        f"Добре, орієнтуємося на {vehicle}{suffix}. "
        "Якщо хочете, можемо подивитися кілька актуальних "
        "варіантів під ці параметри на торгах. Цікаво?"
    )


async def try_deterministic_qualification(
    user_id: int,
    user_text: str,
):
    """
    Просте уточнення параметрів більше НЕ віддаємо Qwen.

    Qwen залишається консультантом для реальних питань.
    Python керує тільки пам'яттю та послідовністю простих уточнень.
    """
    state = get_state(user_id)
    language = state.get('language', 'uk')

    # Не заважаємо спеціальним flow.
    # Якщо лід уже переданий менеджеру — qualification завершено.
    # Далі бот просто консультує клієнта й НЕ пропонує підбір повторно.
    if (
        state.get('lead_sent')
        or state.get('waiting_for_phone')
        or state.get('waiting_for_sea_vehicle')
        or state.get('smart_logistics_pending')
        or state.get('selection_offered')
    ):
        return None

    if looks_like_consultation_question(user_text):
        return None

    memory = get_dialog_memory(user_id)

    before_has_brand = bool(memory.get('brand'))
    before_has_model = bool(memory.get('model'))

    # Оновлюємо структуровану пам'ять ДО вибору наступного кроку.
    update_dialog_memory_from_user(
        user_id,
        user_text,
    )

    memory = get_dialog_memory(user_id)

    brand = (
        memory.get('brand', [])[-1]
        if memory.get('brand')
        else None
    )

    # Додатково фіксуємо модель жорстко.
    model_candidate = extract_model_from_message(
        user_text,
        memory,
    )

    if model_candidate:
        add_unique_memory(
            memory,
            'model',
            model_candidate,
            limit=5,
        )
        add_unique_memory(
            memory,
            'vehicle_request',
            model_candidate,
            limit=6,
        )
        save_persistent_dialog_data()

    model = (
        memory.get('model', [])[-1]
        if memory.get('model')
        else None
    )

    years = memory.get('years', [])
    mileage = memory.get('mileage', [])
    trim = memory.get('trim', [])

    # Якщо це взагалі не автомобільний qualification-контекст — не втручаємось.
    if not brand and not model:
        return None

    # Перевіряємо сумісність модель + рік через Tavily,
    # перш ніж питати наступний параметр.
    if brand and model and years and current_message_has_year(user_text):
        web_context = await get_web_verification_context(
            user_id,
            user_text,
        )

        conflict = await check_model_year_conflict(
            user_id=user_id,
            user_text=user_text,
            web_context=web_context,
            language=language,
        )

        if conflict:
            return conflict

    # Марка є, моделі ще немає.
    if brand and not model:
        if language == 'ru':
            return f"Какая именно модель {brand} Вас интересует?"
        return f"Яка саме модель {brand} Вас цікавить?"

    # Марка + модель є, року нема.
    if brand and model and not years:
        vehicle = f"{brand} {model}".strip()
        if language == 'ru':
            return f"Хорошо, {vehicle}. Какой год или диапазон лет рассматриваете?"
        return f"Добре, {vehicle}. Який рік або діапазон років розглядаєте?"

    # Роки вже відомі — не змушуємо обирати один рік.
    if brand and model and years and not mileage:
        vehicle = qualification_summary(memory)
        if language == 'ru':
            return f"Хорошо, ориентируемся на {vehicle}. По пробегу есть пожелания?"
        return f"Добре, орієнтуємося на {vehicle}. По пробігу є побажання?"

    # Пробіг є — можна ще м'яко уточнити комплектацію.
    if brand and model and years and mileage and not trim:
        vehicle = qualification_summary(memory)
        if language == 'ru':
            return f"Хорошо, {vehicle}. По комплектации есть пожелания?"
        return f"Добре, {vehicle}. По комплектації є побажання?"

    # Запит уже достатньо сформований — робимо ненав'язливий soft-offer.
    if brand and model and years and mileage and trim:
        state['selection_offered'] = True
        state['selection_declined'] = False
        return qualification_soft_offer(
            language,
            memory,
        )

    # Якщо клієнт сам надав нестандартний набір параметрів,
    # але базовий запит уже зрозумілий — віддаємо далі Qwen.
    return None


def update_dialog_memory_from_user(
    user_id: int,
    text: str,
):
    """
    Структурована пам'ять діалогу.

    Важлива відмінність:
    ми пам'ятаємо не тільки текст реплік,
    а й окремо brand/model/year/mileage/trim...
    """

    memory = get_dialog_memory(
        user_id
    )

    clean = " ".join(
        str(text).split()
    )

    if not clean:
        return

    low = clean.lower()

    # --------------------------------------
    # Контекст попереднього питання
    # --------------------------------------

    last_topic = memory.get(
        "last_question_topic"
    )

    store_contextual_answer(
        memory,
        last_topic,
        clean,
    )

    # --------------------------------------
    # Марка
    # --------------------------------------

    detected_brand = detect_brand_name(
        clean
    )

    if detected_brand:
        add_unique_memory(
            memory,
            "brand",
            detected_brand,
            limit=3,
        )

    # --------------------------------------
    # Модель: детермінований детектор
    # --------------------------------------

    explicit_model = extract_model_from_message(
        clean,
        memory,
    )

    if explicit_model:
        add_unique_memory(
            memory,
            "model",
            explicit_model,
            limit=5,
        )

        add_unique_memory(
            memory,
            "vehicle_request",
            explicit_model,
            limit=6,
        )

    # --------------------------------------
    # Модель: додатковий страховочний детектор
    # --------------------------------------

    common_model_pattern = re.fullmatch(
        r"(?i)(?:"
        r"(?:xm|ix|i\d|[xmqz]\d{1,2})|"
        r"\d{3}[a-z]{0,2}|"
        r"[a-z]\-?class|"
        r"gle\s*\d*|glc\s*\d*|gls\s*\d*|"
        r"q\d|"
        r"model\s*[3sxy]|"
        r"r1s|r1t|r2|r3|"
        r"cherokee|grand\s+cherokee"
        r")",
        clean.strip(),
    )

    if (
        common_model_pattern
        and len(clean) <= 30
    ):
        add_unique_memory(
            memory,
            "model",
            clean,
            limit=5,
        )

        add_unique_memory(
            memory,
            "vehicle_request",
            clean,
            limit=6,
        )

    # --------------------------------------
    # Телефон / коротка згода
    # --------------------------------------

    digits = re.sub(
        r"\D",
        "",
        clean,
    )

    is_probable_phone = (
        10 <= len(digits) <= 15
        and len(clean.split()) <= 4
    )

    short_ack = low in {
        "так",
        "да",
        "ні",
        "нет",
        "ок",
        "окей",
        "добре",
        "хорошо",
        "дякую",
        "спасибо",
    }

    if (
        not short_ack
        and not is_probable_phone
    ):
        add_unique_memory(
            memory,
            "client_statements",
            clean,
            limit=16,
        )

    # --------------------------------------
    # Роки
    # --------------------------------------

    years = re.findall(
        r"\b(?:19[8-9]\d|20[0-3]\d)\b",
        clean,
    )

    for year in years:
        add_unique_memory(
            memory,
            "years",
            year,
            limit=6,
        )

    # --------------------------------------
    # Загальний автомобільний запит
    # --------------------------------------

    if detected_brand:
        add_unique_memory(
            memory,
            "vehicle_request",
            clean,
            limit=6,
        )

    # Якщо це була відповідь на "яка модель?"
    # дублюємо її в vehicle_request, щоб вона була
    # особливо помітною у контексті Qwen.
    if (
        last_topic == "model"
        and looks_like_short_slot_reply(
            clean
        )
    ):
        add_unique_memory(
            memory,
            "vehicle_request",
            clean,
            limit=6,
        )

    # --------------------------------------
    # Бюджет
    # --------------------------------------

    if any(
        token in low
        for token in [
            "бюджет",
            "под ключ",
            "під ключ",
            "дол",
            "usd",
            "$",
        ]
    ):
        add_unique_memory(
            memory,
            "budget",
            clean,
            limit=5,
        )

    # --------------------------------------
    # Пробіг
    # --------------------------------------

    if any(
        token in low
        for token in [
            "пробег",
            "пробіг",
            "км",
            "миль",
        ]
    ):
        add_unique_memory(
            memory,
            "mileage",
            clean,
            limit=5,
        )

    # --------------------------------------
    # Двигун
    # --------------------------------------

    if any(
        token in low
        for token in [
            "двиг",
            "мотор",
            "бензин",
            "дизел",
            "атмосфер",
            "турбо",
            "2.0",
            "2.5",
            "3.0",
            "3.5",
            "5.0",
            "6.2",
        ]
    ):
        add_unique_memory(
            memory,
            "engine",
            clean,
            limit=5,
        )

    # --------------------------------------
    # Привід
    # --------------------------------------

    if any(
        token in low
        for token in [
            "xdrive",
            "quattro",
            "awd",
            "fwd",
            "rwd",
            "полный привод",
            "повний привід",
            "передний привод",
            "передній привід",
            "задний привод",
            "задній привід",
        ]
    ):
        add_unique_memory(
            memory,
            "drive",
            clean,
            limit=5,
        )

    # --------------------------------------
    # Батарея
    # --------------------------------------

    if any(
        token in low
        for token in [
            "квт",
            "kwh",
            "батаре",
            "аккумуля",
            "акумуля",
        ]
    ):
        add_unique_memory(
            memory,
            "battery",
            clean,
            limit=5,
        )

    # --------------------------------------
    # Комплектація
    # --------------------------------------

    if any(
        token in low
        for token in [
            "комплектац",
            "максимал",
            "топов",
            "limited",
            "premium",
            "platinum",
            "sel",
            "se ",
            "gt line",
            "gt-line",
            "lariat",
            "overland",
        ]
    ):
        add_unique_memory(
            memory,
            "trim",
            clean,
            limit=5,
        )

    # --------------------------------------
    # Колір
    # --------------------------------------

    if any(
        token in low
        for token in [
            "черн",
            "чорн",
            "бел",
            "білий",
            "біла",
            "сер",
            "син",
            "красн",
            "червон",
            "зел",
            "gray",
            "grey",
            "black",
            "white",
            "blue",
            "red",
        ]
    ):
        add_unique_memory(
            memory,
            "color",
            clean,
            limit=5,
        )

    save_persistent_dialog_data()


def remember_assistant_questions(
    user_id: int,
    answer: str,
):
    """
    Зберігаємо питання + тему ОСТАННЬОГО питання.
    """

    memory = get_dialog_memory(
        user_id
    )

    parts = re.split(
        r"(?<=[?])\s+|\n+",
        answer,
    )

    for part in parts:
        part = " ".join(
            part.split()
        ).strip()

        if "?" in part:
            add_unique_memory(
                memory,
                "asked_questions",
                part,
                limit=14,
            )

    memory[
        "last_question_topic"
    ] = detect_question_topic(
        answer
    )

    save_persistent_dialog_data()


def build_dialog_memory_context(
    user_id: int,
):
    memory = get_dialog_memory(
        user_id
    )

    current_vehicle = (
        build_current_vehicle_summary(
            memory
        )
    )

    lines = [
        "==========================================",
        "ПАМ'ЯТЬ ПОТОЧНОГО ДІАЛОГУ — ВИСОКИЙ ПРІОРИТЕТ",
        "==========================================",
        "",
        "Це вже ВІДОМІ факти від клієнта.",
        "Не змушуй клієнта повідомляти їх повторно.",
        "",
    ]

    if current_vehicle:
        lines.append(
            "ПОТОЧНИЙ ЗАПИТ: "
            + current_vehicle
        )

        lines.append(
            "КРИТИЧНО: марка/модель/роки вище вже відомі. "
            "Не починай вибір автомобіля заново."
        )

        lines.append("")

    labels = [
        (
            "brand",
            "Марка",
        ),
        (
            "model",
            "Модель",
        ),
        (
            "years",
            "Рік / діапазон років",
        ),
        (
            "budget",
            "Бюджет",
        ),
        (
            "mileage",
            "Пробіг",
        ),
        (
            "trim",
            "Комплектація",
        ),
        (
            "engine",
            "Двигун / паливо",
        ),
        (
            "drive",
            "Привід",
        ),
        (
            "battery",
            "Батарея",
        ),
        (
            "color",
            "Колір",
        ),
        (
            "preferences",
            "Інші побажання",
        ),
    ]

    has_facts = False

    for key, label in labels:
        values = memory.get(
            key,
            [],
        )

        if values:
            has_facts = True

            lines.append(
                f"{label}: "
                + " | ".join(
                    values[-5:]
                )
            )

    statements = memory.get(
        "client_statements",
        [],
    )

    if statements:
        has_facts = True

        lines.append("")
        lines.append(
            "Останні твердження клієнта:"
        )

        for statement in statements[-10:]:
            lines.append(
                f"- {statement}"
            )

    asked = memory.get(
        "asked_questions",
        [],
    )

    if asked:
        lines.append("")
        lines.append(
            "Ти вже ставив ці питання:"
        )

        for question in asked[-10:]:
            lines.append(
                f"- {question}"
            )

    last_topic = memory.get(
        "last_question_topic"
    )

    if last_topic:
        lines.append("")
        lines.append(
            "Останнє уточнення було про: "
            f"{last_topic}"
        )

    lines.extend(
        [
            "",
            "ЖОРСТКІ ПРАВИЛА ПАМ'ЯТІ:",
            "1. Не питай повторно параметр, який уже є вище.",
            "2. Якщо клієнт назвав діапазон років, він НЕ зобов'язаний "
            "обирати один конкретний рік.",
            "3. Коротка відповідь клієнта є відповіддю на твоє попереднє "
            "питання. Не трактуй її як початок нового діалогу.",
            "4. Якщо відомі Mercedes-Benz + S-Class + 2016-2017, "
            "заборонено знову питати марку, модель або рік.",
            "5. Продовжуй з наступного невідомого параметра або відповідай "
            "на конкретне питання клієнта.",
        ]
    )

    if not has_facts:
        lines.append(
            "Структурованих фактів поки немає."
        )

    return "\n".join(
        lines
    )


def get_state(user_id: int):
    if user_id not in user_states:
        user_states[user_id] = {
            "waiting_for_phone": False,
            "phone": None,
            "ended": False,
            "lead_sent": False,
            "do_not_ask_phone": False,
            "waiting_for_logistics_details": False,
            "logistics_intent": None,

            # Якщо для морського тарифу
            # ми попросили модель авто.
            "waiting_for_sea_vehicle": False,
            "sea_auction": None,
            "sea_location": None,

            # Мова поточного діалогу.
            "language": "uk",

            # Lead-first flow
            "selection_offered": False,
            "selection_declined": False,
            "qualification_turns": 0,

            "smart_logistics_pending": False,
            "smart_logistics_needs": [],
            "smart_logistics_auction": None,
            "smart_logistics_locations": None,
            "smart_logistics_vehicle": None,
            "smart_logistics_region": None,
        }

    return user_states[user_id]


def reset_user_dialog(
    user_id: int,
    greeting: str | None = None,
):
    if greeting:
        chat_histories[user_id] = [
            {
                "role": "assistant",
                "content": greeting,
            }
        ]
    else:
        chat_histories[user_id] = []

    user_states[user_id] = {
        "waiting_for_phone": False,
        "phone": None,
        "ended": False,
        "lead_sent": False,
        "do_not_ask_phone": False,
        "waiting_for_logistics_details": False,
        "logistics_intent": None,

        "waiting_for_sea_vehicle": False,
        "sea_auction": None,
        "sea_location": None,

        "language": "uk",

        "selection_offered": False,
        "selection_declined": False,
        "qualification_turns": 0,

        "smart_logistics_pending": False,
        "smart_logistics_needs": [],
        "smart_logistics_auction": None,
        "smart_logistics_locations": None,
        "smart_logistics_vehicle": None,
        "smart_logistics_region": None,
    }

    dialog_memories[user_id] = (
        default_dialog_memory()
    )

    save_persistent_dialog_data()


# ==========================================
# КНОПКИ
# ==========================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="📱 Поділитися номером",
                request_contact=True,
            ),
            KeyboardButton(
                text="👨‍💼 Виклик менеджера",
            ),
        ],
        [
            KeyboardButton(
                text="🔄 Почати новий чат",
            ),
            KeyboardButton(
                text="✅ Завершити чат",
            ),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder=(
        "Напишіть повідомлення..."
    ),
)


# ==========================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ==========================================

async def send_to_admin(
    bot: Bot,
    text: str,
):
    if not ADMIN_CHAT_ID:
        print(
            "ADMIN_CHAT_ID не налаштований"
        )
        return

    try:
        await bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=text,
        )
    except Exception as error:
        print(
            "Помилка відправки "
            f"в адмін-групу: {error}"
        )


def user_info(
    message: Message,
):
    user = message.from_user

    name = (
        user.full_name
        or "Без імені"
    )

    username = (
        f"@{user.username}"
        if user.username
        else "немає"
    )

    return (
        f"Ім'я: {name}\n"
        f"Username: {username}\n"
        f"Telegram ID: {user.id}"
    )


def looks_like_phone(
    text: str,
):
    digits = re.sub(
        r"\D",
        "",
        text,
    )

    return (
        10 <= len(digits) <= 15
    )


def ai_asks_for_phone(
    answer: str,
):
    text = answer.lower()

    phrases = [
        "номер телефону",
        "залиште номер",
        "залиште, будь ласка, номер",
        "поділитися номером",
        "надішліть номер",
        "номер телефона",
        "оставьте номер",
        "оставьте, пожалуйста, номер",
        "поделитесь номером",
        "пришлите номер",
    ]

    return any(
        phrase in text
        for phrase in phrases
    )


def user_forbids_phone_request(
    text: str,
):
    text = text.lower()

    phrases = [
        "не проси номер",
        "не просите номер",
        "номер не дам",
        "не дам номер",
        "не хочу оставлять номер",
        "не хочу залишати номер",
        "не проси телефон",
        "не просите телефон",
    ]

    return any(
        phrase in text
        for phrase in phrases
    )


def normalize_search_text(
    text: str,
):
    text = (
        text.upper()
        .replace("–", "-")
        .replace("—", "-")
    )

    text = re.sub(
        r"[^A-ZА-ЯЁІЇЄҐ0-9]+",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


def get_recent_user_text(
    user_id: int,
    current_text: str,
    limit: int = 8,
):
    parts = []

    for item in (
        chat_histories.get(
            user_id,
            []
        )[-limit:]
    ):
        if (
            item.get("role")
            == "user"
        ):
            parts.append(
                item.get(
                    "content",
                    ""
                )
            )

    parts.append(
        current_text
    )

    return " ".join(parts)


# ==========================================
# ВИЗНАЧЕННЯ АУКЦІОНУ
# ==========================================

def detect_auction(
    text: str,
):
    t = text.upper()

    if "COPART" in t:
        return "Copart"

    if (
        "IAAI" in t
        or "IAA " in t
        or t.endswith("IAA")
    ):
        return "IAAI"

    return None


# ==========================================
# ВИЗНАЧЕННЯ ЛОКАЦІЇ
# ==========================================

def detect_location(
    auction: str,
    text: str,
):
    if not auction:
        return None

    section = (
        PRICE_DATA
        .get("usa", {})
        .get(auction, {})
    )

    locations = section.get(
        "locations",
        []
    )

    normalized_text = (
        normalize_search_text(text)
    )

    candidates = []

    for item in locations:
        full_name = (
            item.get(
                "location",
                ""
            )
        )

        if not full_name:
            continue

        base_name = (
            full_name
            .split(" - ")[0]
            .strip()
        )

        base_normalized = (
            normalize_search_text(
                base_name
            )
        )

        full_normalized = (
            normalize_search_text(
                full_name
            )
        )

        # Чим довша назва —
        # тим пріоритетніше співпадіння.
        if (
            base_normalized
            and base_normalized
            in normalized_text
        ):
            candidates.append(
                (
                    len(base_normalized),
                    full_name,
                )
            )

        elif (
            full_normalized
            and full_normalized
            in normalized_text
        ):
            candidates.append(
                (
                    len(full_normalized),
                    full_name,
                )
            )

    if not candidates:
        return None

    candidates.sort(
        reverse=True
    )

    return candidates[0][1]


# ==========================================
# КЛЮЧОВІ СЛОВА ЛОГІСТИКИ
# ==========================================

def is_logistics_question(
    text: str,
):
    t = text.lower()

    keywords = [
        "суша",
        "доставка",
        "порт",
        "море",
        "морем",
        "логіст",
        "логист",
        "shipping",
        "delivery",
        "транспорт",
        "сколько везти",
        "скільки везти",
    ]

    return any(
        word in t
        for word in keywords
    )


def asks_about_ports(
    text: str,
):
    t = text.lower()

    return (
        "порт" in t
    )


# ==========================================
# СПИСОК ПОРТІВ З БАЗИ
# ==========================================

def get_company_ports():
    ports = []

    for auction in [
        "Copart",
        "IAAI",
    ]:
        section = (
            PRICE_DATA
            .get("usa", {})
            .get(auction, {})
        )

        for port in (
            section.get(
                "ports",
                []
            )
        ):
            if (
                port
                and port not in ports
            ):
                ports.append(port)

    return ports




# ==========================================
# ПОСЛУГИ AUCTION AUTO
# ==========================================

def get_company_fee(
    car_price: float,
):
    """
    Тариф послуг Auction Auto
    залежно від ціни покупки авто на аукціоні.
    """

    if car_price < 20000:
        return 750

    if car_price < 30000:
        return 1000

    return 1500


def is_service_fee_question(
    text: str,
):
    t = text.lower()

    keywords = [
        "ваших услуг",
        "ваші послуги",
        "ваших послуг",
        "вартість послуг",
        "стоимость услуг",
        "сколько услуги",
        "скільки послуги",
        "комиссия",
        "комісія",
        "ваша комиссия",
        "ваша комісія",
        "услуги auction auto",
        "послуги auction auto",
    ]

    return any(
        item in t
        for item in keywords
    )


def extract_price_from_text(
    text: str,
):
    """
    Витягує ймовірну вартість авто.

    Розуміє:
    10000
    10 000
    10.000
    10,000
    $10000
    """

    raw_numbers = re.findall(
        r"(?<!\w)\$?\s*(\d[\d\s.,]{2,})",
        text,
    )

    candidates = []

    for raw in raw_numbers:
        cleaned = re.sub(
            r"[^\d]",
            "",
            raw,
        )

        if not cleaned:
            continue

        try:
            value = int(
                cleaned
            )
        except ValueError:
            continue

        # Для тарифу послуг нас цікавить
        # саме ціна авто, а не рік/пробіг.
        if 1000 <= value <= 500000:
            candidates.append(
                value
            )

    if not candidates:
        return None

    # У типовому запиті найбільше число —
    # саме ціна авто.
    return max(
        candidates
    )


def service_fee_answer(
    user_text: str,
    language: str,
):
    if not is_service_fee_question(
        user_text
    ):
        return None

    price = extract_price_from_text(
        user_text
    )

    if price is None:
        if language == "ru":
            return (
                "Стоимость наших услуг зависит только от цены покупки "
                "автомобиля на аукционе. Напишите ориентировочную цену авто."
            )

        return (
            "Вартість наших послуг залежить тільки від ціни покупки "
            "автомобіля на аукціоні. Напишіть орієнтовну ціну авто."
        )

    fee = get_company_fee(
        price
    )

    if language == "ru":
        return (
            f"При цене автомобиля ${price:,} на аукционе "
            f"стоимость услуг Auction Auto — ${fee:,}."
        ).replace(",", " ")

    return (
        f"При вартості автомобіля ${price:,} на аукціоні "
        f"послуги Auction Auto коштують ${fee:,}."
    ).replace(",", " ")


# ==========================================
# LEAD-FIRST FLOW
# ==========================================

def is_affirmative(
    text: str,
):
    """
    Розуміє не тільки точне "Так"/"Да",
    а й:
    "Так, 2020 року"
    "Да, давайте"
    "Окей, передавайте"
    """

    t = text.lower().strip()

    # Явна відмова не повинна випадково
    # спрацювати як згода через перше слово "да/так".
    negative_starts = [
        "да не",
        "так не",
        "нет",
        "ні",
        "не треба",
        "не надо",
    ]

    if any(
        t.startswith(item)
        for item in negative_starts
    ):
        return False

    exact_phrases = {
        "так",
        "да",
        "ок",
        "окей",
        "добре",
        "хорошо",
        "давай",
        "давайте",
        "звісно",
        "конечно",
        "цікаво",
        "интересно",
        "хочу",
        "погнали",
        "поехали",
    }

    if t in exact_phrases:
        return True

    # Перше слово може бути "Так," / "Да," / "Окей,"
    normalized = re.sub(
        r"[^\wа-яёіїєґ]+",
        " ",
        t,
        flags=re.IGNORECASE,
    ).strip()

    first_word = (
        normalized.split()[0]
        if normalized
        else ""
    )

    if first_word in {
        "так",
        "да",
        "ок",
        "окей",
        "добре",
        "хорошо",
        "звісно",
        "конечно",
    }:
        return True

    return any(
        phrase in t
        for phrase in [
            "да, интересно",
            "так, цікаво",
            "давайте посмотрим",
            "давайте посмотрим варианты",
            "давайте подберем",
            "давайте підберемо",
            "хочу варианты",
            "хочу варіанти",
            "покажите варианты",
            "покажіть варіанти",
            "передавайте",
            "передавайте менеджеру",
            "передавайте запит",
            "передавайте запрос",
        ]
    )

def is_negative(
    text: str,
):
    return text.lower().strip() in {
        "нет",
        "ні",
        "не",
        "пока нет",
        "поки ні",
        "не сейчас",
        "не зараз",
    }


def explicitly_wants_selection(
    text: str,
):
    t = text.lower()

    phrases = [
        "подбери варианты",
        "подберите варианты",
        "покажи варианты",
        "покажите варианты",
        "хочу варианты",
        "хочу подобрать",
        "хочу підбір",
        "підбери варіанти",
        "підберіть варіанти",
        "покажи варіанти",
        "покажіть варіанти",
        "актуальные лоты",
        "актуальні лоти",
        "актуальные варианты",
        "актуальні варіанти",
        "свяжите с менеджером",
        "зв'яжіть з менеджером",
        "связаться с менеджером",
        "хочу заказать",
        "хочу замовити",
        "готов покупать",
        "готов купувати",
    ]

    return any(
        phrase in t
        for phrase in phrases
    )


def ask_phone_for_lead_text(
    language: str,
):
    if language == "ru":
        return (
            "Отлично 👍 Тогда передам запрос менеджеру на подбор "
            "актуальных вариантов. Оставьте номер телефона или "
            "нажмите «📱 Поділитися номером»."
        )

    return (
        "Чудово 👍 Тоді передам запит менеджеру на підбір "
        "актуальних варіантів. Залиште номер телефону або "
        "натисніть «📱 Поділитися номером»."
    )



def answer_offers_manager_transfer(
    answer: str,
):
    """
    Визначає, що AI вже зробила м'яку пропозицію
    подивитися/підібрати актуальні варіанти.

    Це страховка на випадок, якщо Qwen забула
    службовий маркер <OFFER_SELECTION>.
    """

    t = answer.lower()

    phrases = [
        "подивитись підбірку",
        "подивитися підбірку",
        "переглянути підбірку",
        "підібрати кілька варіантів",
        "підібрати актуальні варіанти",
        "подивитися актуальні варіанти",
        "подивитись актуальні варіанти",
        "переглянути актуальні варіанти",
        "подобрать несколько вариантов",
        "подобрать актуальные варианты",
        "посмотреть подборку",
        "посмотреть актуальные варианты",
        "показать актуальные варианты",
        "глянуть актуальные варианты",
        "подивитися, що зараз є",
        "подивитись, що зараз є",
        "посмотреть, что сейчас есть",
        "передати ваш запит менеджеру",
        "передати запит менеджеру",
        "передать ваш запрос менеджеру",
        "передать запрос менеджеру",
    ]

    if any(
        phrase in t
        for phrase in phrases
    ):
        return True

    has_options = any(
        phrase in t
        for phrase in [
            "актуальні варіанти",
            "актуальные варианты",
            "підбірку варіантів",
            "подборку вариантов",
            "актуальні лоти",
            "актуальные лоты",
        ]
    )

    has_invitation = any(
        phrase in t
        for phrase in [
            "якщо хочете",
            "якщо цікаво",
            "хотіли б",
            "можемо",
            "если хотите",
            "если интересно",
            "хотели бы",
            "можем",
        ]
    )

    return (
        has_options
        and has_invitation
    )


def decline_selection_text(
    language: str,
):
    if language == "ru":
        return (
            "Без проблем 👍 Продолжим здесь. "
            "Спрашивайте, что ещё интересно по машине."
        )

    return (
        "Без проблем 👍 Продовжимо тут. "
        "Питайте, що ще цікавить по авто."
    )


# ==========================================
# ПРЯМА ЛОГІКА ЛОГІСТИКИ
# ==========================================

def detect_message_language(
    text: str,
    previous: str = "uk",
):
    """
    Визначає мову тільки якщо в повідомленні
    є достатньо ознак.

    Якщо повідомлення нейтральне:
    "BMW 530i", "Copart", "ок" тощо —
    зберігаємо мову попереднього діалогу.
    """

    t = text.lower()

    # Унікальні українські літери.
    if re.search(r"[іїєґ]", t):
        return "uk"

    # Унікальні російські літери.
    if re.search(r"[ыэъё]", t):
        return "ru"

    ukrainian_words = [
        "скільки",
        "який",
        "яка",
        "які",
        "підкаж",
        "будь ласка",
        "ціна",
        "вартість",
        "цікавить",
        "потрібно",
        "можна",
        "повний",
        "привід",
        "чорна",
        "доставка",
    ]

    russian_words = [
        "сколько",
        "какой",
        "какая",
        "какие",
        "подскажи",
        "пожалуйста",
        "цена",
        "интересует",
        "нужно",
        "можно",
        "полный",
        "привод",
        "черная",
        "доставка",
        "море",
        "суша",
        "что",
        "это",
    ]

    uk_score = sum(
        1 for word in ukrainian_words
        if word in t
    )

    ru_score = sum(
        1 for word in russian_words
        if word in t
    )

    if uk_score > ru_score:
        return "uk"

    if ru_score > uk_score:
        return "ru"

    return previous


def detect_reply_language(text: str):
    # Залишено для сумісності зі старими викликами.
    return detect_message_language(
        text,
        previous="ru",
    )

def detect_logistics_intent(text: str):
    t = text.lower()

    if any(word in t for word in [
        "суша",
        "по сша",
        "по америке",
        "по штатам",
        "доставка по сша",
        "доставка по америке",
    ]):
        return "land"

    if "порт" in t:
        return "ports"

    if any(word in t for word in [
        "море",
        "морем",
        "морская",
        "морський",
    ]):
        return "sea"

    if any(word in t for word in [
        "доставка",
        "логистика",
        "логістика",
    ]):
        return "delivery"

    return None


def format_location_short(location: str):
    if not location:
        return ""

    return location.split(" - ")[0].strip()


def get_us_company_ports_only():
    excluded = {
        "TORONTO",
        "JEBEL ALI (EMIRATES)",
    }

    result = []

    for port in get_company_ports():
        if normalize_search_text(port) in {
            normalize_search_text(x)
            for x in excluded
        }:
            continue

        if port not in result:
            result.append(port)

    return result


def remember_manual_exchange(
    user_id: int,
    user_text: str,
    assistant_text: str,
):
    history = chat_histories.setdefault(
        user_id,
        [],
    )

    history.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    history.append(
        {
            "role": "assistant",
            "content": assistant_text,
        }
    )

    if len(history) > 30:
        chat_histories[user_id] = history[-30:]

    update_dialog_memory_from_user(
        user_id,
        user_text,
    )

    remember_assistant_questions(
        user_id,
        assistant_text,
    )

    save_persistent_dialog_data()


def make_land_route_text(
    auction: str,
    result: dict,
    language: str,
):
    location = format_location_short(
        result.get("location", "")
    )

    routes = result.get("routes", [])

    if not routes:
        if language == "uk":
            return (
                f"По {auction} {location} маршрут у прайсі є, "
                "але вартість доставки не вказана — її треба уточнити."
            )

        return (
            f"По {auction} {location} маршрут в прайсе есть, "
            "но стоимость доставки не указана — её нужно уточнить."
        )

    normal_routes = [
        route for route in routes
        if route.get("price", {}).get("status")
        in {"ok", "range"}
    ]

    if not normal_routes:
        port_names = ", ".join(
            str(route.get("port"))
            for route in routes
            if route.get("port")
        )

        if language == "uk":
            return (
                f"По {auction} {location} напрямок: {port_names}. "
                "Вартість по цій локації потрібно уточнити."
            )

        return (
            f"По {auction} {location} направление: {port_names}. "
            "Стоимость по этой локации нужно уточнить."
        )

    if len(normal_routes) == 1:
        route = normal_routes[0]
        port = route.get("port")
        price_text = route["price"]["text"]

        if language == "uk":
            return (
                f"З {auction} {location} доставка по США — "
                f"{price_text}, відправка через {port}."
            )

        return (
            f"С {auction} {location} доставка по США — "
            f"{price_text}, отправка через {port}."
        )

    parts = []

    for route in normal_routes:
        parts.append(
            f"{route.get('port')} — "
            f"{route['price']['text']}"
        )

    joined = "; ".join(parts)

    if language == "uk":
        return (
            f"По {auction} {location} у прайсі є кілька маршрутів: "
            f"{joined}."
        )

    return (
        f"По {auction} {location} в прайсе есть несколько маршрутов: "
        f"{joined}."
    )



# ==========================================
# КАТЕГОРІЯ АВТО ДЛЯ МОРСЬКОГО ТАРИФУ
# ==========================================

async def classify_vehicle_for_shipping(
    vehicle_text: str,
):
    """
    Qwen тут НЕ рахує ціну і НЕ відповідає клієнту.

    Спочатку перевіряємо очевидні категорії кодом.
    Якщо категорія не очевидна — Qwen лише класифікує авто.
    """

    t = vehicle_text.lower()

    if any(word in t for word in [
        "седан", "sedan", "купе", "coupe",
        "хэтч", "хетч", "hatch", "wagon",
        "универсал", "універсал",
    ]):
        return {
            "category": "Small vehicle/Coupe/Sedan",
            "is_ev_hybrid": (
                True
                if any(x in t for x in [
                    "electric", "электро", "електро",
                    "hybrid", "гибрид", "гібрид",
                ])
                else False
            ),
        }

    if any(word in t for word in [
        "кроссовер", "кросовер", "crossover",
        "suv", "пикап", "пікап", "pickup",
    ]):
        return {
            "category": "Crossover/SUV/Standard Truck",
            "is_ev_hybrid": (
                True
                if any(x in t for x in [
                    "electric", "электро", "електро",
                    "hybrid", "гибрид", "гібрид",
                ])
                else False
            ),
        }

    if any(word in t for word in [
        "мотоцикл", "motorcycle",
    ]):
        return {
            "category": "Motorcycle",
            "is_ev_hybrid": False,
        }

    prompt = """
Ти класифікатор автомобілів для логістичної таблиці.

За назвою автомобіля визнач ТІЛЬКИ категорію
та тип силової установки.

Допустимі категорії:
SEDAN = sedan, coupe, hatchback, wagon та звичайне легкове авто
SUV = crossover, SUV, standard pickup/truck
EXTRA = дуже велике авто, dually, vehicle over 20 ft
MOTORCYCLE = звичайний мотоцикл
LARGE_MOTORCYCLE = великий/важкий мотоцикл
UNKNOWN = неможливо визначити

EV:
YES = електромобіль або гібрид
NO = бензин/дизель
UNKNOWN = неможливо визначити

Відповідай РІВНО одним рядком у форматі:
CATEGORY=SEDAN;EV=NO

Не додавай пояснення.
Не рахуй ціни.
"""

    try:
        raw = await ollama_chat(
            messages=[
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": vehicle_text,
                },
            ],
            num_predict=30,
            temperature=0.0,
        )
    except Exception as error:
        print(
            "Помилка класифікації авто:",
            error,
        )

        return {
            "category": None,
            "is_ev_hybrid": None,
        }

    upper = raw.upper()

    category = None

    if "CATEGORY=LARGE_MOTORCYCLE" in upper:
        category = "Large Motorcycle"

    elif "CATEGORY=MOTORCYCLE" in upper:
        category = "Motorcycle"

    elif "CATEGORY=EXTRA" in upper:
        category = (
            "Extra Large Vehicle/"
            "Dually/Over 20 ft."
        )

    elif "CATEGORY=SUV" in upper:
        category = (
            "Crossover/SUV/"
            "Standard Truck"
        )

    elif "CATEGORY=SEDAN" in upper:
        category = (
            "Small vehicle/"
            "Coupe/Sedan"
        )

    is_ev_hybrid = None

    if "EV=YES" in upper:
        is_ev_hybrid = True

    elif "EV=NO" in upper:
        is_ev_hybrid = False

    return {
        "category": category,
        "is_ev_hybrid": is_ev_hybrid,
    }


def clean_rate_value(value):
    """
    Форматує тариф з JSON.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            value = int(value)

        return f"${value}"

    if isinstance(value, dict):
        if "min" in value and "max" in value:
            return (
                f"${value['min']}–"
                f"${value['max']}"
            )

        return None

    return None


async def answer_pending_sea_vehicle(
    user_id: int,
    vehicle_text: str,
):
    """
    Якщо перед цим бот сказав:
    "Напишите модель" —
    наступне повідомлення трактуємо
    як модель для морського тарифу.
    """

    state = get_state(user_id)

    if not state.get(
        "waiting_for_sea_vehicle",
        False,
    ):
        return None

    auction = state.get(
        "sea_auction"
    )

    location = state.get(
        "sea_location"
    )

    language = state.get(
        "language",
        "uk",
    )

    # Не скидаємо стан, доки не спробуємо
    # реально визначити категорію.
    classification = (
        await classify_vehicle_for_shipping(
            vehicle_text
        )
    )

    category = classification.get(
        "category"
    )

    is_ev_hybrid = classification.get(
        "is_ev_hybrid"
    )

    if not category:
        if language == "uk":
            return (
                "Не зміг точно визначити категорію цього авто. "
                "Це легкове авто, кросовер/SUV, пікап чи мотоцикл?"
            )

        return (
            "Не смог точно определить категорию этого авто. "
            "Это легковой автомобиль, кроссовер/SUV, пикап или мотоцикл?"
        )

    result = get_best_usa_route(
        auction,
        location,
    )

    if not result:
        state["waiting_for_sea_vehicle"] = False
        state["sea_auction"] = None
        state["sea_location"] = None

        if language == "uk":
            return (
                "Не вдалося підтягнути маршрут із прайсу. "
                "Цю вартість потрібно уточнити."
            )

        return (
            "Не удалось подтянуть маршрут из прайса. "
            "Эту стоимость нужно уточнить."
        )

    routes = result.get(
        "routes",
        [],
    )

    if not routes:
        state["waiting_for_sea_vehicle"] = False

        if language == "uk":
            return (
                "Для цієї локації в прайсі немає "
                "доступного маршруту."
            )

        return (
            "Для этой локации в прайсе нет "
            "доступного маршрута."
        )

    # Зазвичай в таблиці один робочий маршрут.
    route = routes[0]
    port = route.get("port")

    rates = get_vehicle_rates(
        auction,
        category,
    )

    sea_value = None

    if rates:
        sea_value = rates.get(
            port
        )

    sea_text = clean_rate_value(
        sea_value
    )

    state["waiting_for_sea_vehicle"] = False
    state["sea_auction"] = None
    state["sea_location"] = None

    if not sea_text:
        if language == "uk":
            return (
                f"Для {vehicle_text} через {port} "
                "морський тариф у базі не підтягнувся — "
                "його потрібно уточнити."
            )

        return (
            f"Для {vehicle_text} через {port} "
            "морской тариф из базы не подтянулся — "
            "его нужно уточнить."
        )

    ev_fee_text = None

    if is_ev_hybrid:
        ev_rates = get_vehicle_rates(
            auction,
            "Electrical/Hybrid FEE",
        )

        if ev_rates:
            ev_fee_text = clean_rate_value(
                ev_rates.get(port)
            )

    if language == "uk":
        answer = (
            f"Для {vehicle_text} через {port} "
            f"морський тариф — {sea_text}."
        )

        if ev_fee_text:
            answer += (
                f" Для електро/гібрида додатково "
                f"EV/Hybrid fee — {ev_fee_text}."
            )

        return answer

    answer = (
        f"Для {vehicle_text} через {port} "
        f"морской тариф — {sea_text}."
    )

    if ev_fee_text:
        answer += (
            f" Для электро/гибрида дополнительно "
            f"EV/Hybrid fee — {ev_fee_text}."
        )

    return answer



# ==========================================
# SMART LOGISTICS
# ==========================================

def detect_logistics_needs_smart(
    text: str,
):
    """
    Повертає набір того, що просить клієнт.

    Працюємо по коренях слів, щоб розуміти:
    "суша", "суші", "суше";
    "море", "морю", "морем";
    "доставка", "доставки", "доставку".
    """

    t = text.lower()

    needs = set()

    if (
        "суш" in t
        or "по сша" in t
        or "по америк" in t
        or "по штат" in t
    ):
        needs.add("land")

    if "мор" in t:
        needs.add("sea")

    if "порт" in t:
        needs.add("port")

    if (
        "достав" in t
        or "логіст" in t
        or "логист" in t
        or "shipping" in t
    ):
        # Якщо клієнт уже уточнив сушу/море,
        # generic delivery не додаємо.
        if not needs:
            needs.add("delivery")

    return needs


def cyrillic_to_latin_simple(
    text: str,
):
    """
    Спрощена транслітерація для пошуку назв
    американських аукціонних локацій.

    Це НЕ використовується для показу клієнту.
    Тільки для зіставлення введення:
    "Савані" -> SAVANI -> SAVANNAH
    "Макон" -> MAKON -> MACON
    "Атланта Норт" -> ATLANTA NORT -> ATLANTA NORTH
    """

    mapping = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "ґ": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "є": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "і": "i",
        "ї": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }

    result = []

    for char in text.lower():
        result.append(
            mapping.get(
                char,
                char,
            )
        )

    return "".join(result)



LOCATION_TEXT_ALIASES = {
    # Savannah
    "саванна": "SAVANNAH",
    "савана": "SAVANNAH",
    "савані": "SAVANNAH",
    "саванне": "SAVANNAH",
    "саванну": "SAVANNAH",
    "саванне": "SAVANNAH",

    # Macon
    "макон": "MACON",
    "мейкон": "MACON",

    # Atlanta North
    "атланта норт": "ATLANTA NORTH",
    "атланта север": "ATLANTA NORTH",
    "атланта північ": "ATLANTA NORTH",

    # Atlanta East / West / South
    "атланта ист": "ATLANTA EAST",
    "атланта схід": "ATLANTA EAST",
    "атланта вест": "ATLANTA WEST",
    "атланта захід": "ATLANTA WEST",
    "атланта саут": "ATLANTA SOUTH",
    "атланта південь": "ATLANTA SOUTH",
}


def apply_location_aliases(
    text: str,
):
    """
    Додає до пошукового тексту канонічну
    англійську назву, якщо бачимо поширений alias.
    """

    lower = text.lower()
    additions = []

    for alias, canonical in (
        LOCATION_TEXT_ALIASES.items()
    ):
        if alias in lower:
            additions.append(
                canonical
            )

    if additions:
        return (
            text
            + " "
            + " ".join(additions)
        )

    return text


def location_search_variants(
    text: str,
):
    """
    Робимо два варіанти:
    1. оригінальний текст;
    2. транслітерований у латиницю.
    """

    aliased_text = apply_location_aliases(
        text
    )

    variants = [
        normalize_search_text(
            aliased_text
        ),
        normalize_search_text(
            cyrillic_to_latin_simple(
                aliased_text
            )
        ),
    ]

    # Прибираємо дублікати.
    result = []

    for item in variants:
        if item and item not in result:
            result.append(item)

    return result


def best_fuzzy_location_score(
    query_text: str,
    location_name: str,
):
    """
    Порівнюємо назву локації не з усім реченням,
    а з фрагментами відповідної довжини.

    Наприклад:
    "В САВАНІ" -> "V SAVANI"
    "SAVANI" порівнюється з "SAVANNAH".
    """

    query_tokens = (
        normalize_search_text(
            query_text
        ).split()
    )

    location_tokens = (
        normalize_search_text(
            location_name
        ).split()
    )

    if not query_tokens or not location_tokens:
        return 0.0

    needed = len(
        location_tokens
    )

    candidates = []

    # Одинарні/багатослівні n-grams.
    for size in {
        max(1, needed - 1),
        needed,
        needed + 1,
    }:
        if size > len(query_tokens):
            continue

        for i in range(
            0,
            len(query_tokens) - size + 1,
        ):
            fragment = " ".join(
                query_tokens[
                    i:i + size
                ]
            )

            candidates.append(
                fragment
            )

    # Для коротких назв також перевіряємо
    # кожне окреме слово.
    candidates.extend(
        query_tokens
    )

    target = " ".join(
        location_tokens
    )

    best = 0.0

    for fragment in candidates:
        score = SequenceMatcher(
            None,
            fragment,
            target,
        ).ratio()

        if score > best:
            best = score

    return best



# ==========================================
# ШТАТ / РЕГІОН США
# ==========================================

US_STATE_ALIASES = {
    "new york": "New York",
    "нью йорк": "New York",
    "нью-йорк": "New York",
    "ньюйорк": "New York",

    "new jersey": "New Jersey",
    "нью джерси": "New Jersey",
    "нью-джерси": "New Jersey",

    "georgia": "Georgia",
    "джорджия": "Georgia",
    "джорджія": "Georgia",

    "florida": "Florida",
    "флорида": "Florida",

    "texas": "Texas",
    "техас": "Texas",

    "california": "California",
    "калифорния": "California",
    "каліфорнія": "California",

    "illinois": "Illinois",
    "иллинойс": "Illinois",
    "іллінойс": "Illinois",

    "pennsylvania": "Pennsylvania",
    "пенсильвания": "Pennsylvania",
    "пенсильванія": "Pennsylvania",

    "ohio": "Ohio",
    "огайо": "Ohio",

    "missouri": "Missouri",
    "миссури": "Missouri",
    "міссурі": "Missouri",
}


def detect_us_state(
    text: str,
):
    low = (
        text.lower()
        .replace("ё", "е")
    )

    for alias, canonical in (
        US_STATE_ALIASES.items()
    ):
        if alias in low:
            return canonical

    return None


def get_locations_in_state(
    state_name: str,
):
    """
    Повертає реальні аукціонні локації з JSON
    для конкретного штату.
    """

    result = {}

    for auction in [
        "Copart",
        "IAAI",
    ]:
        rows = []

        section = (
            PRICE_DATA
            .get("usa", {})
            .get(auction, {})
        )

        for item in section.get(
            "locations",
            []
        ):
            location = item.get(
                "location",
                ""
            )

            if (
                state_name.lower()
                in location.lower()
            ):
                rows.append(
                    location
                )

        if rows:
            result[auction] = rows

    return result


def state_locations_question(
    state_name: str,
    language: str,
):
    locations = get_locations_in_state(
        state_name
    )

    names = []

    for auction, rows in (
        locations.items()
    ):
        for location in rows:
            short = (
                location
                .split(" - ")[0]
                .strip()
            )

            item = (
                f"{short} ({auction})"
            )

            if item not in names:
                names.append(item)

    if not names:
        if language == "ru":
            return (
                f"По штату {state_name} точную локацию "
                "в нашем прайсе не нашёл. Нужна конкретная "
                "площадка аукциона."
            )

        return (
            f"По штату {state_name} точну локацію "
            "в нашому прайсі не знайшов. Потрібна конкретна "
            "площадка аукціону."
        )

    shown = ", ".join(
        names[:12]
    )

    if language == "ru":
        return (
            f"{state_name} — это штат, и в нашем прайсе там "
            f"несколько площадок: {shown}. "
            "Уточните конкретную локацию — тогда скажу точную "
            "стоимость доставки."
        )

    return (
        f"{state_name} — це штат, і в нашому прайсі там "
        f"кілька площадок: {shown}. "
        "Уточніть конкретну локацію — тоді скажу точну "
        "вартість доставки."
    )


def detect_location_across_auctions(
    text: str,
):
    """
    Шукає локацію одразу в Copart та IAAI.

    Підтримує:
    - точну англійську назву;
    - часткову англійську назву;
    - українське/російське написання;
    - відмінки та невеликі помилки.

    Приклад:
    "в Савані" -> SAVANNAH - Georgia
    """

    search_variants = (
        location_search_variants(
            text
        )
    )

    result = {}

    for auction in [
        "Copart",
        "IAAI",
    ]:
        section = (
            PRICE_DATA
            .get("usa", {})
            .get(auction, {})
        )

        exact_candidates = []
        fuzzy_candidates = []

        for item in section.get(
            "locations",
            []
        ):
            full_name = (
                item.get(
                    "location",
                    ""
                )
            )

            if not full_name:
                continue

            # Беремо головну назву до " - State".
            base_name = (
                full_name
                .split(" - ")[0]
                .split(" / ")[0]
                .strip()
            )

            base_n = normalize_search_text(
                base_name
            )

            full_n = normalize_search_text(
                full_name
            )

            # ----------------------------------
            # 1. Точний / частковий пошук
            # ----------------------------------

            exact_score = 0

            for variant in search_variants:
                variant_tokens = (
                    variant.split()
                )

                base_tokens = (
                    base_n.split()
                )

                # Короткі коди типу MO/NY/CA
                # НЕ можна шукати як substring.
                # Інакше "морю" -> MORYU помилково
                # знаходить локацію MO.
                if (
                    base_n
                    and len(base_n) <= 3
                ):
                    if (
                        len(base_tokens) == 1
                        and base_n in variant_tokens
                    ):
                        exact_score = max(
                            exact_score,
                            2100 + len(base_n),
                        )

                elif (
                    base_n
                    and base_n in variant
                ):
                    exact_score = max(
                        exact_score,
                        2000 + len(base_n),
                    )

                if (
                    full_n
                    and len(full_n) > 3
                    and full_n in variant
                ):
                    exact_score = max(
                        exact_score,
                        1900 + len(full_n),
                    )

            if exact_score:
                exact_candidates.append(
                    (
                        exact_score,
                        full_name,
                    )
                )

                continue

            # ----------------------------------
            # 2. Fuzzy-пошук для "Савані",
            #    "Макон", "Атланта Норт" тощо
            # ----------------------------------

            # Для коротких кодів типу MO/NY
            # fuzzy search взагалі не використовуємо.
            if len(base_n) <= 3:
                continue

            best_score = 0.0

            for variant in search_variants:
                score = best_fuzzy_location_score(
                    variant,
                    base_n,
                )

                if score > best_score:
                    best_score = score

            if best_score >= 0.70:
                fuzzy_candidates.append(
                    (
                        best_score,
                        full_name,
                    )
                )

        # Точне співпадіння завжди має пріоритет.
        if exact_candidates:
            exact_candidates.sort(
                reverse=True
            )

            result[auction] = (
                exact_candidates[0][1]
            )

            continue

        if fuzzy_candidates:
            fuzzy_candidates.sort(
                reverse=True
            )

            best_score, best_location = (
                fuzzy_candidates[0]
            )

            # Захист від неоднозначного fuzzy match:
            # беремо результат тільки якщо він помітно
            # кращий за другий варіант.
            second_score = (
                fuzzy_candidates[1][0]
                if len(fuzzy_candidates) > 1
                else 0.0
            )

            if (
                best_score >= 0.78
                or (
                    best_score >= 0.70
                    and (
                        best_score
                        - second_score
                    ) >= 0.08
                )
            ):
                result[auction] = (
                    best_location
                )

    return result


def vehicle_hint_from_memory(
    user_id: int,
):
    """
    Бере поточне авто зі структурованої пам'яті.

    Приклад:
    Toyota + Camry + 2018-2020
    -> "Toyota Camry 2018-2020"

    Це потрібно, щоб на "А по морю?"
    бот НЕ питав модель повторно.
    """

    memory = get_dialog_memory(
        user_id
    )

    brand = (
        memory.get(
            "brand",
            [],
        )[-1]
        if memory.get("brand")
        else ""
    )

    model = (
        memory.get(
            "model",
            [],
        )[-1]
        if memory.get("model")
        else ""
    )

    years = memory.get(
        "years",
        [],
    )

    parts = []

    if brand:
        parts.append(
            brand
        )

    if model:
        # Якщо model уже містить бренд,
        # не дублюємо його.
        if (
            not brand
            or brand.lower()
            not in model.lower()
        ):
            parts.append(
                model
            )

    if years:
        if len(years) >= 2:
            parts.append(
                f"{years[-2]}-{years[-1]}"
            )
        else:
            parts.append(
                years[-1]
            )

    result = " ".join(
        part
        for part in parts
        if part
    ).strip()

    return result or None


def extract_vehicle_hint(
    text: str,
):
    """
    Не намагаємось визначати характеристики.
    Просто розуміємо, чи є в тексті назва авто,
    щоб передати її класифікатору кузова.
    """

    t = text.lower()

    brands = [
        "bmw", "бмв",
        "audi", "ауди",
        "mercedes", "мерседес",
        "tesla", "тесла",
        "toyota", "тойота",
        "lexus", "лексус",
        "ford", "форд",
        "chevrolet", "шевроле",
        "dodge", "додж",
        "jeep", "джип",
        "volkswagen", "фольксваген",
        "nissan", "ниссан", "ніссан",
        "kia", "кіа", "киа",
        "hyundai", "хюндай", "хендай",
        "mazda", "мазда",
        "honda", "хонда",
        "subaru", "субару",
        "mitsubishi", "мітсубісі", "митсубиси",
        "volvo", "вольво",
        "porsche", "порше",
        "cadillac", "кадиллак",
        "infiniti", "инфинити",
        "polestar",
        "rivian",
        "land rover",
        "range rover",
        "jaguar", "ягуар",
        "fisker",
        "lincoln", "линкольн",
        "acura",
        "gmc",
        "genesis",
    ]

    if any(
        brand in t
        for brand in brands
    ):
        return text.strip()

    # Клієнт може відповісти просто:
    # "седан", "кросовер", "пікап".
    body_words = [
        "седан", "sedan",
        "кроссовер", "кросовер", "crossover",
        "suv",
        "пикап", "пікап", "pickup",
        "купе", "coupe",
        "хетч", "hatch",
        "универсал", "універсал", "wagon",
        "мотоцикл", "motorcycle",
    ]

    if any(
        word in t
        for word in body_words
    ):
        return text.strip()

    return None


def rate_signature(
    auction: str,
    location: str,
):
    """
    Повертає простий опис наземного маршруту.
    """

    result = get_best_usa_route(
        auction,
        location,
    )

    if not result:
        return None

    routes = []

    for route in result.get(
        "routes",
        []
    ):
        price = route.get(
            "price",
            {}
        )

        routes.append(
            {
                "port": route.get("port"),
                "price_text": price.get(
                    "text",
                    "вартість потрібно уточнити",
                ),
                "price_status": price.get(
                    "status",
                ),
            }
        )

    return {
        "auction": auction,
        "location": result.get(
            "location",
            location,
        ),
        "routes": routes,
    }


def build_land_answer_multi(
    found_locations: dict,
    language: str,
):
    """
    Якщо локація є на кількох аукціонах,
    не змушуємо клієнта одразу уточнювати аукціон.

    Показуємо тарифи по кожному аукціону.
    """

    rows = []

    for auction, location in (
        found_locations.items()
    ):
        signature = rate_signature(
            auction,
            location,
        )

        if not signature:
            continue

        for route in signature[
            "routes"
        ]:
            rows.append(
                {
                    "auction": auction,
                    "location": signature[
                        "location"
                    ],
                    "port": route["port"],
                    "price": route[
                        "price_text"
                    ],
                    "status": route[
                        "price_status"
                    ],
                }
            )

    if not rows:
        return None

    # Якщо по всіх аукціонах тариф і порт однакові —
    # відповідаємо однією цифрою.
    unique_pairs = {
        (
            row["port"],
            row["price"],
        )
        for row in rows
    }

    location_short = (
        format_location_short(
            rows[0]["location"]
        )
    )

    if len(unique_pairs) == 1:
        port, price = next(
            iter(unique_pairs)
        )

        if language == "uk":
            return (
                f"Для {location_short} доставка по США "
                f"до порту {port} — {price}."
            )

        return (
            f"Для {location_short} доставка по США "
            f"до порта {port} — {price}."
        )

    # Якщо Copart та IAAI мають різні ціни —
    # показуємо обидві, а не перепитуємо те,
    # що можемо пояснити самі.
    parts = []

    for row in rows:
        parts.append(
            f"{row['auction']} — "
            f"{row['price']} до "
            f"{row['port']}"
        )

    joined = "; ".join(parts)

    if language == "uk":
        return (
            f"Для {location_short} тариф залежить "
            f"від аукціону: {joined}."
        )

    return (
        f"Для {location_short} тариф зависит "
        f"от аукциона: {joined}."
    )


async def build_sea_answer_multi(
    found_locations: dict,
    vehicle_hint: str,
    language: str,
):
    """
    Визначає категорію авто, після чого бере
    МОРСЬКИЙ тариф тільки з JSON.
    """

    classification = (
        await classify_vehicle_for_shipping(
            vehicle_hint
        )
    )

    category = classification.get(
        "category"
    )

    is_ev_hybrid = classification.get(
        "is_ev_hybrid"
    )

    if not category:
        if language == "uk":
            return (
                "Для морського тарифу уточніть "
                "тип авто: легкове, кросовер/SUV, "
                "пікап чи мотоцикл."
            )

        return (
            "Для морского тарифа уточните "
            "тип авто: легковое, кроссовер/SUV, "
            "пикап или мотоцикл."
        )

    rows = []

    for auction, location in (
        found_locations.items()
    ):
        route_result = get_best_usa_route(
            auction,
            location,
        )

        if not route_result:
            continue

        for route in route_result.get(
            "routes",
            []
        ):
            port = route.get(
                "port"
            )

            rates = get_vehicle_rates(
                auction,
                category,
            )

            sea_value = (
                rates.get(port)
                if rates
                else None
            )

            sea_text = clean_rate_value(
                sea_value
            )

            ev_fee_text = None

            if is_ev_hybrid:
                ev_rates = get_vehicle_rates(
                    auction,
                    "Electrical/Hybrid FEE",
                )

                if ev_rates:
                    ev_fee_text = clean_rate_value(
                        ev_rates.get(port)
                    )

            rows.append(
                {
                    "auction": auction,
                    "port": port,
                    "sea": sea_text,
                    "ev_fee": ev_fee_text,
                }
            )

    valid_rows = [
        row for row in rows
        if row["sea"]
    ]

    if not valid_rows:
        if language == "uk":
            return (
                "Морський тариф для цієї категорії "
                "у базі не підтягнувся — його потрібно уточнити."
            )

        return (
            "Морской тариф для этой категории "
            "в базе не подтянулся — его нужно уточнить."
        )

    unique_sea = {
        (
            row["port"],
            row["sea"],
            row["ev_fee"],
        )
        for row in valid_rows
    }

    if len(unique_sea) == 1:
        port, sea, ev_fee = next(
            iter(unique_sea)
        )

        if language == "uk":
            answer = (
                f"Морський тариф через {port} "
                f"для цієї категорії авто — {sea}."
            )

            if ev_fee:
                answer += (
                    f" Додатковий EV/Hybrid fee — "
                    f"{ev_fee}."
                )

            return answer

        answer = (
            f"Морской тариф через {port} "
            f"для этой категории авто — {sea}."
        )

        if ev_fee:
            answer += (
                f" Дополнительный EV/Hybrid fee — "
                f"{ev_fee}."
            )

        return answer

    parts = []

    for row in valid_rows:
        item = (
            f"{row['auction']} через "
            f"{row['port']} — {row['sea']}"
        )

        if row["ev_fee"]:
            item += (
                f" + EV/Hybrid fee "
                f"{row['ev_fee']}"
            )

        parts.append(item)

    if language == "uk":
        return (
            "Морський тариф залежить від маршруту: "
            + "; ".join(parts)
            + "."
        )

    return (
        "Морской тариф зависит от маршрута: "
        + "; ".join(parts)
        + "."
    )


async def try_smart_logistics_answer(
    user_id: int,
    user_text: str,
):
    """
    Новий основний логістичний обробник.

    Він не віддає точні тарифи Qwen.
    Qwen використовується тільки як
    класифікатор типу автомобіля.
    """

    state = get_state(
        user_id
    )

    current_needs = (
        detect_logistics_needs_smart(
            user_text
        )
    )

    pending = state.get(
        "smart_logistics_pending",
        False,
    )

    if not current_needs and not pending:
        return None

    language = state.get(
        "language",
        "uk",
    )

    # Якщо клієнт назвав тільки штат (наприклад New York),
    # не маємо права вгадувати конкретну площадку.
    state_name = detect_us_state(
        user_text
    )

    if state_name:
        specific_in_current = (
            detect_location_across_auctions(
                user_text
            )
        )

        # Якщо конкретної площадки в самому повідомленні нема,
        # пояснюємо, що потрібна точна локація.
        if not specific_in_current:
            state[
                "smart_logistics_pending"
            ] = True

            state[
                "smart_logistics_region"
            ] = state_name

            if current_needs:
                state[
                    "smart_logistics_needs"
                ] = list(
                    current_needs
                )

            return state_locations_question(
                state_name,
                language,
            )

    # Зберігаємо, що саме хотів клієнт.
    if current_needs:
        remembered_needs = set(
            state.get(
                "smart_logistics_needs",
                [],
            )
        )

        remembered_needs.update(
            current_needs
        )

        state[
            "smart_logistics_needs"
        ] = list(
            remembered_needs
        )

    needs = set(
        state.get(
            "smart_logistics_needs",
            [],
        )
    )

    if not needs:
        needs = {
            "delivery"
        }

    combined_text = (
        get_recent_user_text(
            user_id,
            user_text,
            limit=10,
        )
    )

    # -------------------------
    # Аукціон
    # -------------------------

    current_auction = detect_auction(
        user_text
    )

    if current_auction:
        state[
            "smart_logistics_auction"
        ] = current_auction

    auction = state.get(
        "smart_logistics_auction"
    )

    # -------------------------
    # Локація
    # -------------------------

    current_locations = (
        detect_location_across_auctions(
            user_text
        )
    )

    if current_locations:
        state[
            "smart_logistics_locations"
        ] = current_locations

        # Конкретну площадку вже отримали —
        # штат більше не потрібен.
        state[
            "smart_logistics_region"
        ] = None

    found_locations = state.get(
        "smart_logistics_locations"
    )

    # Якщо в поточному повідомленні локація
    # не знайшлася — пробуємо весь контекст.
    if not found_locations:
        found_locations = (
            detect_location_across_auctions(
                combined_text
            )
        )

        if found_locations:
            state[
                "smart_logistics_locations"
            ] = found_locations

    # Якщо клієнт явно назвав аукціон —
    # залишаємо тільки його локацію.
    if auction and found_locations:
        if auction in found_locations:
            found_locations = {
                auction: found_locations[
                    auction
                ]
            }

        else:
            # Пробуємо знайти локацію саме
            # в названому аукціоні по контексту.
            specific_location = (
                detect_location(
                    auction,
                    combined_text,
                )
            )

            if specific_location:
                found_locations = {
                    auction: specific_location
                }

    # -------------------------
    # Модель / тип авто
    # -------------------------

    current_vehicle = (
        extract_vehicle_hint(
            user_text
        )
    )

    if current_vehicle:
        state[
            "smart_logistics_vehicle"
        ] = current_vehicle

    vehicle_hint = state.get(
        "smart_logistics_vehicle"
    )

    # Найнадійніше джерело — структурована пам'ять діалогу.
    # Якщо клієнт уже обговорює Toyota Camry,
    # на "А по морю?" не просимо модель повторно.
    if not vehicle_hint:
        memory_vehicle = (
            vehicle_hint_from_memory(
                user_id
            )
        )

        if memory_vehicle:
            vehicle_hint = memory_vehicle
            state[
                "smart_logistics_vehicle"
            ] = memory_vehicle

    # Fallback — шукаємо назву авто в недавніх репліках.
    if not vehicle_hint:
        recent_vehicle = (
            extract_vehicle_hint(
                combined_text
            )
        )

        if recent_vehicle:
            vehicle_hint = recent_vehicle
            state[
                "smart_logistics_vehicle"
            ] = recent_vehicle

    # -------------------------
    # Що ще потрібно уточнити
    # -------------------------

    if not found_locations:
        state[
            "smart_logistics_pending"
        ] = True

        if language == "uk":
            return (
                "Напишіть локацію аукціону, "
                "де знаходиться авто — наприклад "
                "ATLANTA NORTH або MACON."
            )

        return (
            "Напишите локацию аукциона, "
            "где находится авто — например "
            "ATLANTA NORTH или MACON."
        )

    # Якщо є generic delivery, але нема
    # уточнення суша/море — трактуємо як сушу.
    if needs == {"delivery"}:
        needs = {
            "land"
        }

    # -------------------------
    # Будуємо відповідь
    # -------------------------

    answers = []

    if "land" in needs:
        land_answer = (
            build_land_answer_multi(
                found_locations,
                language,
            )
        )

        if land_answer:
            answers.append(
                land_answer
            )

    if "port" in needs:
        ports = []

        for auc, loc in (
            found_locations.items()
        ):
            result = get_best_usa_route(
                auc,
                loc,
            )

            if not result:
                continue

            for route in result.get(
                "routes",
                []
            ):
                port = route.get(
                    "port"
                )

                if (
                    port
                    and port not in ports
                ):
                    ports.append(
                        port
                    )

        if ports:
            if language == "uk":
                answers.append(
                    "Відправка йде через "
                    + ", ".join(ports)
                    + "."
                )
            else:
                answers.append(
                    "Отправка идёт через "
                    + ", ".join(ports)
                    + "."
                )

    if "sea" in needs:
        if not vehicle_hint:
            state[
                "smart_logistics_pending"
            ] = True

            # Землю можемо сказати вже зараз,
            # а для моря попросити тільки модель.
            if language == "uk":
                sea_question = (
                    "Для морського тарифу напишіть "
                    "модель або тип авто."
                )
            else:
                sea_question = (
                    "Для морского тарифа напишите "
                    "модель или тип авто."
                )

            if answers:
                answers.append(
                    sea_question
                )

                return " ".join(
                    answers
                )

            return sea_question

        sea_answer = (
            await build_sea_answer_multi(
                found_locations,
                vehicle_hint,
                language,
            )
        )

        if sea_answer:
            answers.append(
                sea_answer
            )

    # Усе потрібне вже порахували.
    state[
        "smart_logistics_pending"
    ] = False

    state[
        "smart_logistics_needs"
    ] = []

    state[
        "smart_logistics_auction"
    ] = None

    state[
        "smart_logistics_locations"
    ] = None

    state[
        "smart_logistics_vehicle"
    ] = None

    if answers:
        return " ".join(
            answers
        )

    return None


async def try_direct_logistics_answer(
    user_id: int,
    user_text: str,
):
    """
    Повертає готову відповідь БЕЗ Qwen,
    якщо питання стосується тарифів/портів.

    Це спеціально зроблено, щоб AI
    не вигадував цифри та не ігнорував JSON.
    """

    state = get_state(user_id)

    current_intent = detect_logistics_intent(
        user_text
    )

    is_pending = state.get(
        "waiting_for_logistics_details",
        False,
    )

    if not current_intent and not is_pending:
        return None

    intent = (
        current_intent
        or state.get("logistics_intent")
        or "delivery"
    )

    language = detect_reply_language(
        user_text
    )

    combined_text = get_recent_user_text(
        user_id,
        user_text,
        limit=10,
    )

    # Якщо людина питає загальний список портів,
    # а не конкретну локацію.
    if (
        intent == "ports"
        and not detect_auction(combined_text)
    ):
        ports = get_us_company_ports_only()

        state["waiting_for_logistics_details"] = False
        state["logistics_intent"] = None

        if language == "uk":
            return (
                "У нашому прайсі по США є такі напрямки: "
                + ", ".join(ports)
                + "."
            )

        return (
            "В нашем прайсе по США есть такие направления: "
            + ", ".join(ports)
            + "."
        )

    auction = detect_auction(
        combined_text
    )

    if not auction:
        state["waiting_for_logistics_details"] = True
        state["logistics_intent"] = intent

        if language == "uk":
            return (
                "Уточніть, будь ласка, аукціон — Copart чи IAAI — "
                "і локацію автомобіля."
            )

        return (
            "Уточните, пожалуйста, аукцион — Copart или IAAI — "
            "и локацию автомобиля."
        )

    location = detect_location(
        auction,
        combined_text,
    )

    if not location:
        state["waiting_for_logistics_details"] = True
        state["logistics_intent"] = intent

        if language == "uk":
            return (
                f"Аукціон {auction} бачу. "
                "Напишіть ще локацію автомобіля — перевірю тариф."
            )

        return (
            f"Аукцион {auction} вижу. "
            "Напишите ещё локацию автомобиля — проверю тариф."
        )

    result = get_best_usa_route(
        auction,
        location,
    )

    state["waiting_for_logistics_details"] = False
    state["logistics_intent"] = None

    if not result:
        if language == "uk":
            return (
                f"Локацію {location} знайшов, але тариф у базі "
                "не підтягнувся. Тут краще уточнити вартість."
            )

        return (
            f"Локацию {location} нашёл, но тариф из базы "
            "не подтянулся. Здесь лучше уточнить стоимость."
        )

    # Суша / загальна доставка з конкретної площадки
    if intent in {"land", "delivery"}:
        return make_land_route_text(
            auction,
            result,
            language,
        )

    # Порт для конкретної площадки
    if intent == "ports":
        routes = result.get("routes", [])

        ports = [
            str(route.get("port"))
            for route in routes
            if route.get("port")
        ]

        location_short = format_location_short(
            result.get("location", "")
        )

        land_text = make_land_route_text(
            auction,
            result,
            language,
        )

        if language == "uk":
            if ports:
                return (
                    f"Для {auction} {location_short} у нашому прайсі "
                    f"маршрут іде через {', '.join(ports)}. "
                    + land_text
                )

            return land_text

        if ports:
            return (
                f"Для {auction} {location_short} в нашем прайсе "
                f"маршрут идёт через {', '.join(ports)}. "
                + land_text
            )

        return land_text

    # Море: запам'ятовуємо контекст і чекаємо модель авто.
    if intent == "sea":
        routes = result.get("routes", [])

        ports = [
            str(route.get("port"))
            for route in routes
            if route.get("port")
        ]

        location_short = format_location_short(
            result.get("location", "")
        )

        state["waiting_for_sea_vehicle"] = True
        state["sea_auction"] = auction
        state["sea_location"] = location

        if language == "uk":
            return (
                f"З {auction} {location_short} авто йде через "
                f"{', '.join(ports)}. Напишіть модель авто — "
                "скажу морський тариф по нашому прайсу."
            )

        return (
            f"С {auction} {location_short} авто идёт через "
            f"{', '.join(ports)}. Напишите модель автомобиля — "
            "скажу морской тариф по нашему прайсу."
        )

    return None


# ==========================================
# VERIFIED BUSINESS CONTEXT
# ==========================================

def build_verified_context(
    user_id: int,
    user_text: str,
):
    """
    Ця функція шукає перевірені дані
    в прайсі компанії.

    Qwen не повинна вигадувати
    логістичні тарифи сама.
    """

    if not is_logistics_question(
        user_text
    ):
        return (
            "Для поточного повідомлення "
            "додаткові логістичні дані "
            "з бази не запитувались."
        )

    combined_text = (
        get_recent_user_text(
            user_id,
            user_text,
        )
    )

    auction = detect_auction(
        combined_text
    )

    location = detect_location(
        auction,
        combined_text,
    )

    lines = [
        "ПЕРЕВІРЕНІ ДАНІ "
        "AUCTION AUTO:",
    ]

    if asks_about_ports(
        user_text
    ):
        ports = get_company_ports()

        lines.append(
            "Порти/напрямки, "
            "які присутні "
            "у внутрішньому прайсі:"
        )

        for port in ports:
            lines.append(
                f"- {port}"
            )

    if not auction:
        lines.append(
            "Аукціон не визначений."
        )

        lines.append(
            "Якщо клієнт питає "
            "вартість доставки "
            "з конкретної площадки, "
            "потрібно уточнити "
            "аукціон і локацію."
        )

        return "\n".join(lines)

    lines.append(
        f"Аукціон: {auction}"
    )

    if not location:
        lines.append(
            "Конкретна локація "
            "аукціону не визначена."
        )

        lines.append(
            "Для точної вартості "
            "доставки по США "
            "уточни локацію."
        )

        return "\n".join(lines)

    result = get_best_usa_route(
        auction,
        location,
    )

    if not result:
        lines.append(
            f"Локація: {location}"
        )

        lines.append(
            "Тариф у базі "
            "не знайдено."
        )

        return "\n".join(lines)

    lines.append(
        f"Локація: "
        f"{result['location']}"
    )

    lines.append(
        "Доступні маршрути "
        "по США:"
    )

    for route in (
        result.get(
            "routes",
            []
        )
    ):
        price_info = route[
            "price"
        ]

        lines.append(
            f"- порт "
            f"{route['port']}: "
            f"{price_info['text']}"
        )

        # Додаємо морські тарифи
        # для всіх категорій,
        # але Qwen має використати
        # лише відповідну категорію.
        port = route["port"]

        lines.append(
            f"  Морські/портові "
            f"тарифи через {port}:"
        )

        categories = [
            "Small vehicle/Coupe/Sedan",
            "Crossover/SUV/Standard Truck",
            "Extra Large Vehicle/Dually/Over 20 ft.",
            "Motorcycle",
            "Large Motorcycle",
            "Electrical/Hybrid FEE",
            "СТОЯНКА",
        ]

        for category in categories:
            rates = get_vehicle_rates(
                auction,
                category,
            )

            if (
                rates
                and port in rates
            ):
                lines.append(
                    f"  - {category}: "
                    f"${rates[port]}"
                )

    lines.append(
        "ВАЖЛИВО: використовуй "
        "тільки ці перевірені "
        "дані. Не додавай інші "
        "порти або тарифи "
        "зі своїх загальних знань."
    )

    return "\n".join(lines)




# ==========================================
# PRICE GUARD
# ==========================================

def is_company_service_question(
    text: str,
):
    return is_service_fee_question(
        text
    )


def is_logistics_price_question(
    text: str,
):
    return is_logistics_question(
        text
    )


def is_vehicle_price_question(
    text: str,
):
    """
    Визначає запит саме про ЦІНУ АВТО,
    а не про доставку чи послуги компанії.
    """

    t = text.lower()

    # Ці теми мають свої точні Python-обробники.
    if is_company_service_question(text):
        return False

    if is_logistics_price_question(text):
        return False

    price_phrases = [
        "сколько стоит",
        "скільки коштує",
        "какая цена",
        "яка ціна",
        "что по цене",
        "що по ціні",
        "по цене",
        "по ціні",
        "стоимость авто",
        "вартість авто",
        "стоимость машины",
        "вартість машини",
        "во сколько выйдет",
        "в скільки вийде",
        "сколько выйдет",
        "скільки вийде",
        "сколько будет стоить",
        "скільки буде коштувати",
        "примерная цена",
        "приблизна ціна",
        "примерно по цене",
        "приблизно по ціні",
        "дай вилку",
        "дайте вилку",
        "ценовой диапазон",
        "діапазон ціни",
        "за сколько можно",
        "за скільки можна",
        "под ключ",
        "під ключ",
    ]

    if any(
        phrase in t
        for phrase in price_phrases
    ):
        return True

    # Короткі запити:
    # "цена?"
    # "стоимость?"
    # "вартість?"
    stripped = t.strip(
        " ?!.,"
    )

    if stripped in {
        "цена",
        "ціна",
        "стоимость",
        "вартість",
        "примерно",
        "приблизно",
        "вилка",
    }:
        return True

    return False


def safe_vehicle_price_answer(
    language: str,
):
    """
    Бот НЕ вигадує ринкову/аукціонну ціну авто,
    доки в нас немає реального джерела актуальних лотів.
    """

    if language == "ru":
        return (
            "По самой машине не хочу называть случайную цену — "
            "без актуальных лотов она может сильно отличаться из-за "
            "года, пробега, комплектации и повреждений. "
            "Давайте сформируем параметры, и потом можно передать "
            "запрос менеджеру на актуальный подбор."
        )

    return (
        "По самому авто не хочу називати випадкову ціну — "
        "без актуальних лотів вона може сильно відрізнятися через "
        "рік, пробіг, комплектацію та пошкодження. "
        "Давайте сформуємо параметри, а потім можна передати "
        "запит менеджеру на актуальний підбір."
    )


def contains_money_amount(
    text: str,
):
    """
    Ловимо гроші, які Qwen намагається придумати сама.

    Приклади:
    $25 000
    25,000 USD
    25000 доларів
    30 тис. $
    """

    patterns = [
        r"\$\s*\d",
        r"\d[\d\s.,]*\s*(?:usd|долар|доллар|дол\.|бакс)",
        r"\d[\d\s.,]*\s*(?:€|eur|евро|євро)",
    ]

    low = text.lower()

    return any(
        re.search(
            pattern,
            low,
            flags=re.IGNORECASE,
        )
        for pattern in patterns
    )



def answer_mentions_wrong_vehicle_brand(
    user_id: int,
    user_text: str,
    answer: str,
):
    """
    Якщо ми обговорюємо Rivian, а Qwen раптом пише BMW,
    відповідь блокується.

    Якщо сам клієнт попросив порівняти дві марки —
    чужа марка дозволяється.
    """

    memory = get_dialog_memory(
        user_id
    )

    current_brand = (
        memory.get(
            "brand",
            [],
        )[-1]
        if memory.get("brand")
        else None
    )

    if not current_brand:
        return None

    user_low = user_text.lower()
    answer_low = answer.lower()

    canonical_brands = sorted(
        set(
            BRAND_ALIASES.values()
        )
    )

    for other_brand in canonical_brands:
        if (
            other_brand
            == current_brand
        ):
            continue

        aliases = [
            alias
            for alias, canonical
            in BRAND_ALIASES.items()
            if canonical == other_brand
        ]

        user_mentions_other = any(
            alias in user_low
            for alias in aliases
        )

        answer_mentions_other = any(
            alias in answer_low
            for alias in aliases
        )

        if (
            answer_mentions_other
            and not user_mentions_other
        ):
            return other_brand

    return None


def remove_unsupported_ai_price(
    answer: str,
    language: str,
):
    """
    Остання страховка.

    Якщо звичайна Qwen-відповідь містить грошову цифру,
    якої не дав Python із перевіреної бази,
    ми НЕ показуємо її клієнту.
    """

    if not contains_money_amount(
        answer
    ):
        return answer

    print(
        "PRICE GUARD: заблоковано "
        "непідтверджену грошову цифру Qwen:",
        answer,
    )

    if language == "ru":
        return (
            "По точной стоимости не хочу давать Вам неподтверждённую "
            "цифру. Такие суммы нужно считать по актуальному лоту "
            "и нашим проверенным тарифам."
        )

    return (
        "По точній вартості не хочу давати Вам непідтверджену "
        "цифру. Такі суми потрібно рахувати по актуальному лоту "
        "та наших перевірених тарифах."
    )


# ==========================================
# DOMAIN GUARD
# ==========================================

AUTOMOTIVE_KEYWORDS = [
    # Загальні слова
    "авто", "автомоб", "машин", "vehicle", "car",
    "двигун", "двигател", "мотор", "коробк", "акпп",
    "автомат", "варіатор", "вариатор", "dsg", "aisin",
    "батаре", "акумуля", "аккумуля", "квт", "kwh",
    "пробіг", "пробег", "комплектац", "привод",
    "awd", "fwd", "rwd", "xdrive", "quattro",
    "гібрид", "гибрид", "електро", "электро", "ev",
    "дизел", "бензин", "атмосфер", "турбо",
    "кузов", "седан", "кроссовер", "suv", "пікап", "пикап",
    "хетч", "універсал", "универсал", "купе",
    "vin", "він", "винкод", "вин-код",

    # Купівля / аукціони / логістика
    "аукцион", "аукціон", "copart", "iaai", "manheim",
    "лот", "торг", "ставк", "buy now",
    "достав", "логіст", "логист", "порт", "море", "суша",
    "розмит", "растамож", "мит", "тамож", "брокер",
    "сертиф", "експедитор", "экспедитор",
    "під ключ", "под ключ", "carfax", "карфакс",

    # Популярні марки
    "bmw", "бмв", "audi", "ауди", "mercedes", "мерседес",
    "tesla", "тесла", "toyota", "тойота", "lexus", "лексус",
    "ford", "форд", "chevrolet", "шевроле", "dodge", "додж",
    "jeep", "джип", "volkswagen", "фольксваген", " vw ",
    "nissan", "ниссан", "ніссан", "kia", "кіа", "киа",
    "hyundai", "хюндай", "хендай", "mazda", "мазда",
    "honda", "хонда", "subaru", "субару", "mitsubishi",
    "мітсубісі", "митсубиси", "volvo", "вольво",
    "porsche", "порше", "cadillac", "кадиллак",
    "infiniti", "инфинити", "polestar", "rivian",
    "land rover", "range rover", "jaguar", "ягуар",
    "fisker", "lincoln", "линкольн", "mini", "acura",
    "buick", "gmc", "chrysler", "genesis",
]

OFFTOPIC_KEYWORDS = [
    # Їжа / рецепти
    "рецепт", "млинц", "блин", "борщ", "суп", "салат",
    "пицц", "піцца", "котлет", "каша", "кукуруз", "кукурудз",
    "торт", "пирог", "омлет", "готовить", "готувати",

    # Явно сторонні теми
    "погод", "гороскоп", "анекдот", "стих", "вірш",
    "футбол", "баскетбол", "теннис", "теніс",
    "политик", "політик", "выбор", "вибор",
    "курс валют", "биткоин", "біткоїн",
    "домашк", "реферат", "математик",
]

SHORT_ALLOWED = {
    "да", "так", "нет", "ні", "ок", "окей", "добре",
    "хорошо", "понял", "поняла", "зрозумів", "зрозуміла",
    "спасибо", "дякую", "понятно", "ясно",
    "привет", "здравствуйте", "добрый день",
    "добрий день", "вітаю", "добрый вечер",
    "добрий вечір", "погнали", "поехали",
    "давай", "давайте", "почали", "начали",
}


def get_offtopic_reply(language: str):
    if language == "ru":
        return (
            "Я здесь консультирую только по автомобилям и услугам "
            "Auction Auto 🙂 Могу помочь с подбором авто, "
            "характеристиками, аукционами, доставкой и тарифами."
        )

    return (
        "Я тут консультую лише щодо автомобілів і послуг "
        "Auction Auto 🙂 Можу допомогти з підбором авто, "
        "характеристиками, аукціонами, доставкою та тарифами."
    )


def quick_domain_decision(
    user_id: int,
    user_text: str,
):
    """
    True  = точно дозволена тема.
    False = точно стороння тема.
    None  = неоднозначно, перевіряємо коротким LLM-класифікатором.
    """

    state = get_state(user_id)
    t = user_text.lower().strip()

    # Якщо ми самі чекаємо конкретну відповідь клієнта,
    # не блокуємо її domain guard'ом.
    if (
        state.get("waiting_for_phone")
        or state.get("waiting_for_logistics_details")
        or state.get("waiting_for_sea_vehicle")
    ):
        return True

    if t in SHORT_ALLOWED:
        return True

    # "Ты робот?" / питання про самого консультанта — дозволяємо.
    if any(x in t for x in [
        "ты робот", "ти робот", "это бот", "це бот",
        "ты человек", "ти людина", "кто ты", "хто ти",
    ]):
        return True

    # Явний офтоп блокуємо до будь-якого виклику консультанта.
    if any(word in t for word in OFFTOPIC_KEYWORDS):
        return False

    padded = f" {t} "

    if any(word in padded for word in AUTOMOTIVE_KEYWORDS):
        return True

    # Коротка репліка у вже автомобільному діалозі часто є
    # природним follow-up: "а 2021?", "черная", "до 70 тыс" тощо.
    recent = " ".join(
        item.get("content", "")
        for item in chat_histories.get(user_id, [])[-8:]
    ).lower()

    recent_is_auto = any(
        word in f" {recent} "
        for word in AUTOMOTIVE_KEYWORDS
    )

    if recent_is_auto and len(t.split()) <= 6:
        return True

    return None


async def llm_domain_check(
    user_id: int,
    user_text: str,
):
    """
    Дуже короткий окремий класифікатор.

    Він НЕ відповідає клієнту.
    Повертає лише ALLOWED / OFFTOPIC.
    """

    recent_lines = []

    for item in chat_histories.get(
        user_id,
        [],
    )[-8:]:
        role = item.get("role", "")
        content = item.get("content", "")

        recent_lines.append(
            f"{role}: {content}"
        )

    recent_context = "\n".join(
        recent_lines
    )

    classifier_prompt = """
Ти — строгий маршрутизатор повідомлень для Telegram-консультанта
автомобільної компанії Auction Auto.

Потрібно визначити, чи стосується ОСТАННЄ повідомлення клієнта
дозволеної теми.

ALLOWED:
- автомобілі, моделі, характеристики, комплектації;
- двигуни, коробки, батареї, привід, пробіг;
- підбір або купівля автомобіля;
- аукціони США/Канади, Copart, IAAI, Manheim, лоти, торги;
- доставка, порти, логістика, митниця, розмитнення;
- ціни та тарифи Auction Auto;
- ремонт, обслуговування або технічні питання про авто;
- питання про роботу Auction Auto;
- природне продовження попередньої автомобільної розмови;
- привітання, подяка, коротка відповідь;
- питання "ти робот?" або про самого консультанта.

OFFTOPIC:
- їжа та рецепти;
- погода;
- спорт;
- політика;
- домашні завдання;
- програмування;
- розваги та будь-які інші теми, не пов'язані з авто/Auction Auto.

ВАЖЛИВО:
Навіть якщо раніше говорили про авто, нове явне питання на сторонню
тему (наприклад "напиши рецепт млинців") = OFFTOPIC.

Відповідай РІВНО одним словом:
ALLOWED
або
OFFTOPIC
"""

    messages = [
        {
            "role": "system",
            "content": classifier_prompt,
        },
        {
            "role": "user",
            "content": (
                "Останній контекст:\n"
                f"{recent_context}\n\n"
                "НОВЕ повідомлення клієнта:\n"
                f"{user_text}"
            ),
        },
    ]

    try:
        result = await ollama_chat(
            messages=messages,
            num_predict=8,
            temperature=0.0,
        )

        normalized = result.strip().upper()

        if "OFFTOPIC" in normalized:
            return False

        if "ALLOWED" in normalized:
            return True

    except Exception as error:
        print(
            "DOMAIN GUARD ERROR:",
            error,
        )

    # Якщо класифікатор зламався —
    # не блокуємо потенційного клієнта.
    return True


async def is_allowed_domain(
    user_id: int,
    user_text: str,
):
    quick = quick_domain_decision(
        user_id,
        user_text,
    )

    if quick is not None:
        return quick

    return await llm_domain_check(
        user_id,
        user_text,
    )



# ==========================================
# WEB VERIFICATION — TAVILY
# ==========================================

TRUSTED_AUTO_SOURCE_HINTS = [
    # Виробники / пресцентри
    "bmwgroup.com",
    "bmw.com",
    "mercedes-benz.com",
    "mbusa.com",
    "audi-mediacenter.com",
    "audiusa.com",
    "media.vw.com",
    "volkswagen-newsroom.com",
    "media.ford.com",
    "ford.com",
    "media.chevrolet.com",
    "chevrolet.com",
    "stellantisnorthamerica.com",
    "jeep.com",
    "toyota.com",
    "pressroom.toyota.com",
    "lexus.com",
    "nissan-global.com",
    "global.nissannews.com",
    "hyundainews.com",
    "kia.com",
    "kiamedia.com",
    "hondanews.com",
    "subaru.com",
    "media.subaru.com",
    "mazdausa.com",
    "volvocars.com",
    "porsche.com",
    "newsroom.porsche.com",
    "tesla.com",
    "rivian.com",

    # Державні / технічні
    "nhtsa.gov",
    "fueleconomy.gov",
    "epa.gov",
]


def web_source_priority(
    url: str,
):
    low = str(url).lower()

    for hint in TRUSTED_AUTO_SOURCE_HINTS:
        if hint in low:
            return 100

    # Нормальні вторинні джерела залишаємо,
    # але вони йдуть після офіційних.
    secondary = [
        "edmunds.com",
        "caranddriver.com",
        "motortrend.com",
        "kbb.com",
        "cars.com",
        "autotrader.com",
    ]

    for hint in secondary:
        if hint in low:
            return 50

    return 10


def is_web_technical_question(
    text: str,
):
    """
    Технічні/фактичні питання, для яких Qwen
    не повинна покладатися лише на свою пам'ять.
    """

    t = text.lower()

    keywords = [
        # Існування моделі / роки
        "випускав",
        "выпускал",
        "випускається",
        "выпускается",
        "з якого року",
        "с какого года",
        "до якого року",
        "до какого года",
        "які роки",
        "какие годы",
        "існував",
        "существовал",
        "був такий",
        "был такой",
        "рестайл",
        "поколін",
        "поколен",

        # Техніка
        "двигун",
        "двигатель",
        "мотор",
        "коробк",
        "акпп",
        "автомат",
        "варіатор",
        "вариатор",
        "dsg",
        "aisin",
        "zf",
        "батаре",
        "аккумуля",
        "акумуля",
        "квт",
        "kwh",
        "привід",
        "привод",
        "awd",
        "fwd",
        "rwd",
        "xdrive",
        "quattro",
        "комплектац",
        "trim",
        "запас хода",
        "запас ходу",
        "range",
        "потужн",
        "мощност",
        "л.с",
        "лс",
        "horsepower",
        "крутящий",
        "момент",
        "розгін",
        "разгон",
        "0-100",
        "0–100",
    ]

    return any(
        keyword in t
        for keyword in keywords
    )



def detect_web_fact_intent(
    text: str,
):
    """
    Перетворює вільну фразу клієнта в нормальний
    технічний намір для пошуку.

    Ми НЕ відправляємо Tavily сире повідомлення.
    """

    t = text.lower()

    if any(
        phrase in t
        for phrase in [
            "по рокам",
            "по годам",
            "коли випуска",
            "когда выпуска",
            "з якого року",
            "с какого года",
            "до якого року",
            "до какого года",
            "які роки",
            "какие годы",
            "випускались",
            "випускали",
            "выпускались",
            "выпускали",
            "production year",
            "model year",
        ]
    ):
        return "production_years"

    if any(
        phrase in t
        for phrase in [
            "двигун",
            "двигатель",
            "мотор",
        ]
    ):
        return "engine"

    if any(
        phrase in t
        for phrase in [
            "коробк",
            "акпп",
            "автомат",
            "варіатор",
            "вариатор",
            "transmission",
        ]
    ):
        return "transmission"

    if any(
        phrase in t
        for phrase in [
            "батаре",
            "акумуля",
            "аккумуля",
            "квт",
            "kwh",
        ]
    ):
        return "battery"

    if any(
        phrase in t
        for phrase in [
            "комплектац",
            "trim",
        ]
    ):
        return "trims"

    if any(
        phrase in t
        for phrase in [
            "привід",
            "привод",
            "awd",
            "fwd",
            "rwd",
            "xdrive",
            "quattro",
        ]
    ):
        return "drivetrain"

    if any(
        phrase in t
        for phrase in [
            "потужн",
            "мощност",
            "л.с",
            "horsepower",
        ]
    ):
        return "power"

    if any(
        phrase in t
        for phrase in [
            "запас ходу",
            "запас хода",
            "range",
        ]
    ):
        return "range"

    if any(
        phrase in t
        for phrase in [
            "рестайл",
            "поколін",
            "поколен",
        ]
    ):
        return "generation"

    return "technical_fact"


def build_canonical_web_query(
    brand: str,
    model: str,
    intent: str,
    years: list,
):
    """
    Tavily отримує короткий англомовний запит,
    а не весь текст клієнта.
    """

    vehicle = " ".join(
        part
        for part in [
            brand,
            model,
        ]
        if part
    ).strip()

    intent_queries = {
        "production_years": (
            "production years first model year introduction "
            "official manufacturer"
        ),
        "engine": (
            "engine specifications official manufacturer"
        ),
        "transmission": (
            "transmission gearbox specifications official manufacturer"
        ),
        "battery": (
            "battery capacity kWh official manufacturer"
        ),
        "trims": (
            "trim levels configurations official manufacturer"
        ),
        "drivetrain": (
            "drivetrain AWD RWD FWD official manufacturer"
        ),
        "power": (
            "horsepower power specifications official manufacturer"
        ),
        "range": (
            "EPA range official manufacturer"
        ),
        "generation": (
            "generation facelift model years official manufacturer"
        ),
        "technical_fact": (
            "specifications official manufacturer"
        ),
    }

    suffix = intent_queries.get(
        intent,
        intent_queries["technical_fact"],
    )

    # Роки додаємо лише як перевірювану умову.
    years_text = ""

    if years:
        years_text = (
            " "
            + " ".join(
                years[-3:]
            )
        )

    return (
        f"{vehicle}{years_text} {suffix}"
    ).strip()


def current_message_has_year(
    text: str,
):
    return bool(
        re.search(
            r"\b(?:19[8-9]\d|20[0-3]\d)\b",
            text,
        )
    )


def should_web_verify(
    user_id: int,
    user_text: str,
):
    """
    Web verification запускається тільки тоді,
    коли Python уже точно знає brand + model.

    Це не дає Tavily шукати по фразах типу:
    "по рокам не знаю..."
    """

    if is_company_service_question(
        user_text
    ):
        return False

    if is_logistics_question(
        user_text
    ):
        return False

    if is_vehicle_price_question(
        user_text
    ):
        return False

    memory = get_dialog_memory(
        user_id
    )

    has_brand = bool(
        memory.get(
            "brand",
            [],
        )
    )

    has_model = bool(
        memory.get(
            "model",
            [],
        )
    )

    # Без конкретного авто web search НЕ запускаємо.
    if not (
        has_brand
        and has_model
    ):
        return False

    if is_web_technical_question(
        user_text
    ):
        return True

    if current_message_has_year(
        user_text
    ):
        return True

    if memory.get(
        "last_question_topic"
    ) == "year":
        return True

    return False


def build_web_search_query(
    user_id: int,
    user_text: str,
):
    """
    НІКОЛИ не використовує сире повідомлення клієнта
    як основний search query.

    Query = структурована пам'ять + технічний intent.
    """

    memory = get_dialog_memory(
        user_id
    )

    brand = (
        memory.get(
            "brand",
            [],
        )[-1]
        if memory.get("brand")
        else ""
    )

    model = (
        memory.get(
            "model",
            [],
        )[-1]
        if memory.get("model")
        else ""
    )

    if not brand or not model:
        return ""

    years = memory.get(
        "years",
        [],
    )

    intent = detect_web_fact_intent(
        user_text
    )

    return build_canonical_web_query(
        brand=brand,
        model=model,
        intent=intent,
        years=years,
    )


async def tavily_search(
    query: str,
    max_results: int = 5,
):
    if not TAVILY_API_KEY:
        print(
            "WEB VERIFY: TAVILY_API_KEY "
            "не знайдено в .env"
        )

        return []

    cache_key = query.strip().lower()

    cached = web_search_cache.get(
        cache_key
    )

    now = time.time()

    if cached:
        cached_at = cached.get(
            "time",
            0,
        )

        if (
            now - cached_at
            < WEB_CACHE_TTL_SECONDS
        ):
            print(
                "WEB VERIFY CACHE:",
                query,
            )

            return cached.get(
                "results",
                [],
            )

    headers = {
        "Authorization": (
            f"Bearer {TAVILY_API_KEY}"
        ),
        "Content-Type": (
            "application/json"
        ),
    }

    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }

    timeout = aiohttp.ClientTimeout(
        total=30
    )

    try:
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                TAVILY_SEARCH_URL,
                headers=headers,
                json=payload,
            ) as response:

                if response.status != 200:
                    body = await response.text()

                    print(
                        "WEB VERIFY HTTP ERROR:",
                        response.status,
                        body[:500],
                    )

                    return []

                data = await response.json()

    except Exception as error:
        print(
            "WEB VERIFY ERROR:",
            error,
        )

        return []

    results = data.get(
        "results",
        [],
    )

    # Офіційні джерела вище.
    results = sorted(
        results,
        key=lambda item: (
            web_source_priority(
                item.get(
                    "url",
                    "",
                )
            ),
            float(
                item.get(
                    "score",
                    0,
                )
                or 0
            ),
        ),
        reverse=True,
    )

    web_search_cache[
        cache_key
    ] = {
        "time": now,
        "results": results,
    }

    print(
        "WEB VERIFY SEARCH:",
        query,
        "| results:",
        len(results),
    )

    return results



def normalize_vehicle_token(
    value: str,
):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value).lower(),
    )


def filter_results_for_current_vehicle(
    user_id: int,
    results: list,
):
    """
    Відсікаємо результати, які явно не про поточне авто.

    Наприклад, для Rivian R1S не повинні потрапити
    сторінки про BMW 540.
    """

    memory = get_dialog_memory(
        user_id
    )

    brand = (
        memory.get(
            "brand",
            [],
        )[-1]
        if memory.get("brand")
        else ""
    )

    model = (
        memory.get(
            "model",
            [],
        )[-1]
        if memory.get("model")
        else ""
    )

    brand_token = normalize_vehicle_token(
        brand
    )

    model_token = normalize_vehicle_token(
        model
    )

    if not brand_token or not model_token:
        return []

    filtered = []

    for item in results:
        haystack = (
            str(
                item.get(
                    "title",
                    "",
                )
            )
            + " "
            + str(
                item.get(
                    "content",
                    "",
                )
            )
            + " "
            + str(
                item.get(
                    "url",
                    "",
                )
            )
        )

        normalized = normalize_vehicle_token(
            haystack
        )

        brand_ok = (
            brand_token
            in normalized
        )

        model_ok = (
            model_token
            in normalized
        )

        # Для коротких моделей R1S/X5/Q5 обидва
        # маркери повинні бути присутні.
        if (
            brand_ok
            and model_ok
        ):
            filtered.append(
                item
            )

    print(
        "WEB VERIFY FILTER:",
        f"{brand} {model}",
        "| before:",
        len(results),
        "| after:",
        len(filtered),
    )

    return filtered


def format_web_results(
    query: str,
    results: list,
):
    if not results:
        return ""

    lines = [
        "==========================================",
        "WEB VERIFICATION DATA",
        "==========================================",
        f"Пошуковий запит: {query}",
        "",
        "Нижче — зовнішні веб-джерела.",
        "Для технічних фактів віддавай пріоритет офіційним "
        "джерелам виробника та державним технічним джерелам.",
        "Не вигадуй те, чого немає в цих фрагментах.",
        "",
    ]

    for index, item in enumerate(
        results[:5],
        start=1,
    ):
        title = str(
            item.get(
                "title",
                "",
            )
        ).strip()

        url = str(
            item.get(
                "url",
                "",
            )
        ).strip()

        content = str(
            item.get(
                "content",
                "",
            )
        ).strip()

        # Не роздуваємо prompt.
        if len(content) > 900:
            content = (
                content[:900]
                + "..."
            )

        lines.extend(
            [
                f"[SOURCE {index}]",
                f"Title: {title}",
                f"URL: {url}",
                f"Content: {content}",
                "",
            ]
        )

    lines.extend(
        [
            "ПРАВИЛА:",
            "- WEB DATA використовується для перевірки технічних фактів.",
            "- WEB DATA НЕ є джерелом тарифів Auction Auto.",
            "- Не використовуй веб-ціни автомобілів.",
            "- Якщо джерела суперечать одне одному — не вгадуй.",
        ]
    )

    return "\n".join(
        lines
    )


async def get_web_verification_context(
    user_id: int,
    user_text: str,
):
    if not should_web_verify(
        user_id,
        user_text,
    ):
        return ""

    query = build_web_search_query(
        user_id,
        user_text,
    )

    if not query:
        return ""

    results = await tavily_search(
        query,
        max_results=7,
    )

    results = filter_results_for_current_vehicle(
        user_id,
        results,
    )

    if not results:
        print(
            "WEB VERIFY: немає релевантних "
            "результатів саме по поточному авто"
        )

        return ""

    return format_web_results(
        query,
        results[:5],
    )


def is_model_year_validation_case(
    user_id: int,
    user_text: str,
):
    memory = get_dialog_memory(
        user_id
    )

    return (
        bool(memory.get("brand"))
        and bool(memory.get("model"))
        and bool(memory.get("years"))
        and (
            current_message_has_year(
                user_text
            )
            or memory.get(
                "last_question_topic"
            ) == "year"
        )
    )


async def check_model_year_conflict(
    user_id: int,
    user_text: str,
    web_context: str,
    language: str,
):
    """
    Окремий факт-чекер.

    Він НЕ веде консультацію.
    Він лише перевіряє:
    чи може поточна модель існувати в роках,
    які назвав клієнт.
    """

    if not web_context:
        return None

    if not is_model_year_validation_case(
        user_id,
        user_text,
    ):
        return None

    memory = get_dialog_memory(
        user_id
    )

    vehicle = build_current_vehicle_summary(
        memory
    )

    checker_prompt = """
Ти — строгий автомобільний факт-чекер.

Перевір сумісність МОДЕЛІ АВТОМОБІЛЯ та РОКУ/ДІАПАЗОНУ РОКІВ
виключно за WEB VERIFICATION DATA.

Не оцінюй бюджет, пробіг, комплектацію чи доставку.
Не використовуй власні спогади, якщо web-джерела кажуть інше.

Якщо модель реально випускалась хоча б у частині вказаного
діапазону — STATUS=OK.

Якщо модель однозначно НЕ існувала у вказані роки —
STATUS=CONFLICT.

Якщо веб-даних недостатньо —
STATUS=UNCERTAIN.

Формат відповіді РІВНО такий:

STATUS=OK

або:

STATUS=CONFLICT
REASON=коротко, що саме не сходиться

або:

STATUS=UNCERTAIN
"""

    messages = [
        {
            "role": "system",
            "content": checker_prompt,
        },
        {
            "role": "system",
            "content": web_context,
        },
        {
            "role": "user",
            "content": (
                f"Поточний запит: {vehicle}\n"
                f"Остання репліка клієнта: {user_text}"
            ),
        },
    ]

    try:
        result = await ollama_chat(
            messages=messages,
            num_predict=90,
            temperature=0.0,
        )

    except Exception as error:
        print(
            "WEB FACT CHECK ERROR:",
            error,
        )

        return None

    upper = result.upper()

    if "STATUS=CONFLICT" not in upper:
        return None

    reason = ""

    match = re.search(
        r"REASON=(.+)",
        result,
        flags=re.IGNORECASE
        | re.DOTALL,
    )

    if match:
        reason = (
            match.group(1)
            .strip()
            .splitlines()[0]
            .strip()
        )

    if not reason:
        if language == "ru":
            reason = (
                "модель и указанные годы "
                "не совпадают по найденным источникам"
            )
        else:
            reason = (
                "модель і вказані роки "
                "не збігаються за знайденими джерелами"
            )

    if language == "ru":
        return (
            f"Тут есть несостыковка: {reason}. "
            "Уточните, пожалуйста, модель или годы — "
            "и продолжим по правильным параметрам."
        )

    return (
        f"Тут є нестикування: {reason}. "
        "Уточніть, будь ласка, модель або роки — "
        "і продовжимо вже по правильних параметрах."
    )


# ==========================================
# OLLAMA
# ==========================================


async def groq_chat(
    messages,
    num_predict=220,
    temperature=0.2,
    use_browser_search=False,
):
    """
    Основний сильний консультант.

    Якщо use_browser_search=True,
    GPT-OSS 120B сам шукає інформацію в Інтернеті
    через Groq Browser Search.
    """

    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY не знайдено"
        )

    headers = {
        "Authorization": (
            f"Bearer {GROQ_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": num_predict,
        "reasoning_effort": "low",
        "stream": False,

        # Нам не потрібні технічні citation-маркери
        # у Telegram-відповіді клієнту.
        "citation_options": "disabled",
    }

    if use_browser_search:
        payload["tools"] = [
            {
                "type": "browser_search"
            }
        ]

        # Якщо ми вирішили, що факт треба перевірити —
        # змушуємо модель реально використати браузер.
        payload[
            "tool_choice"
        ] = "required"

    timeout = aiohttp.ClientTimeout(
        total=90
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            GROQ_CHAT_URL,
            headers=headers,
            json=payload,
        ) as response:

            body = await response.text()

            if response.status != 200:
                raise RuntimeError(
                    "Groq HTTP "
                    f"{response.status}: "
                    f"{body[:700]}"
                )

            data = await response.json()

    content = (
        data.get(
            "choices",
            [{}],
        )[0]
        .get(
            "message",
            {},
        )
        .get(
            "content",
            "",
        )
    )

    if not content:
        raise RuntimeError(
            "Groq повернув порожню відповідь"
        )

    return content.strip()


async def consultant_chat(
    messages,
    num_predict=220,
    temperature=0.2,
    use_browser_search=False,
):
    """
    Пріоритет:
    1. Groq GPT-OSS 120B
    2. локальний Ollama qwen3:8b як fallback

    Таким чином бот продовжить працювати,
    навіть якщо Free Plan Groq тимчасово
    вперся в rate limit.
    """

    if GROQ_API_KEY:
        try:
            result = await groq_chat(
                messages=messages,
                num_predict=num_predict,
                temperature=temperature,
                use_browser_search=(
                    use_browser_search
                ),
            )

            print(
                "LLM ENGINE:",
                GROQ_MODEL,
                "| browser:",
                use_browser_search,
            )

            return result

        except Exception as error:
            print(
                "GROQ FALLBACK TO OLLAMA:",
                error,
            )

    return await ollama_chat(
        messages=messages,
        num_predict=num_predict,
        temperature=temperature,
    )


async def ollama_chat(
    messages,
    num_predict=180,
    temperature=0.2,
):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": (
                temperature
            ),
            "num_predict": (
                num_predict
            ),
        },
    }

    timeout = (
        aiohttp.ClientTimeout(
            total=180
        )
    )

    async with (
        aiohttp.ClientSession(
            timeout=timeout
        )
    ) as session:

        async with session.post(
            OLLAMA_URL,
            json=payload,
        ) as response:

            response.raise_for_status()

            data = (
                await response.json()
            )

    return (
        data["message"]["content"]
        .strip()
    )


async def ask_ollama(
    user_id: int,
    user_text: str,
):
    if user_id not in chat_histories:
        chat_histories[user_id] = []

    history = chat_histories[
        user_id
    ]

    history.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    update_dialog_memory_from_user(
        user_id,
        user_text,
    )

    state = get_state(
        user_id
    )

    verified_context = (
        build_verified_context(
            user_id,
            user_text,
        )
    )

    # --------------------------------------------------
    # WEB MODE
    # --------------------------------------------------
    #
    # Якщо є Groq:
    # GPT-OSS 120B сам використовує Browser Search.
    #
    # Tavily + локальний Qwen залишаються резервним
    # варіантом, якщо GROQ_API_KEY відсутній.

    groq_browser_needed = (
        bool(GROQ_API_KEY)
        and (
            is_web_technical_question(
                user_text
            )
            or should_web_verify(
                user_id,
                user_text,
            )
        )
    )

    current_language_for_web = state.get(
        "language",
        "uk",
    )

    if GROQ_API_KEY:
        web_context = (
            "WEB VERIFICATION MODE: "
            "для цього повідомлення Groq Browser Search "
            + (
                "УВІМКНЕНО."
                if groq_browser_needed
                else "не потрібен."
            )
        )

        # Сильна модель з browser_search сама
        # перевіряє суперечності модель/рік.
        conflict_answer = None

    else:
        web_context = (
            await get_web_verification_context(
                user_id,
                user_text,
            )
        )

        conflict_answer = (
            await check_model_year_conflict(
                user_id=user_id,
                user_text=user_text,
                web_context=web_context,
                language=current_language_for_web,
            )
        )

    phone_rule = (
        "Клієнт НЕ забороняв "
        "просити контакт."
    )

    current_language = state.get(
        "language",
        "uk",
    )

    if current_language == "ru":
        language_rule = (
            "КРИТИЧНО: поточна мова клієнта — РОСІЙСЬКА. "
            "Відповідай ПОВНІСТЮ російською мовою. "
            "Не вставляй українські слова та фрази."
        )
    else:
        language_rule = (
            "КРИТИЧНО: поточна мова клієнта — УКРАЇНСЬКА. "
            "Відповідай ПОВНІСТЮ українською мовою."
        )

    style_rule = (
        "КРИТИЧНО ДЛЯ ЦЬОГО ПОВІДОМЛЕННЯ: "
        "дай коротку природну відповідь, максимум 1-3 речення. "
        "Не вітайся повторно, якщо діалог уже розпочатий. "
        "Не став більше одного уточнюючого питання за раз. "
        "ПЕРЕД питанням ОБОВ'ЯЗКОВО перевір блок ПАМ'ЯТЬ ПОТОЧНОГО ДІАЛОГУ. "
        "Не питай параметр повторно, якщо клієнт його вже назвав. "
        "Якщо в пам'яті вже є марка + модель + рік/діапазон років, "
        "КАТЕГОРИЧНО ЗАБОРОНЕНО знову питати марку, модель або рік. "
        "Не став широке питання типу 'рік, бюджет, пробіг чи комплектація?', "
        "якщо частина цих параметрів уже відома. "
        "Не наводь приклади інших автомобілів, якщо поточний автомобіль уже відомий. "
        "Не проси аукціон або локацію, якщо клієнт не питає "
        "про логістику конкретного лота. "
        "Просте уточнення марка/модель/рік/пробіг/комплектація "
        "контролює Python. Якщо ці факти вже є в пам'яті, не змінюй "
        "їх і не починай qualification заново."
    )

    price_rule = (
        "КРИТИЧНО: тобі ЗАБОРОНЕНО самостійно називати будь-яку "
        "грошову суму або діапазон вартості автомобіля. "
        "Не пиши $, USD, долари, євро або випадкові цінові вилки, "
        "якщо конкретну суму не передала система як VERIFIED DATA. "
        "Не використовуй свої загальні знання для оцінки ціни авто."
    )

    web_rule = (
        "ДЛЯ ТЕХНІЧНИХ АВТОМОБІЛЬНИХ ФАКТІВ, коли Browser Search "
        "увімкнений, ОБОВ'ЯЗКОВО перевір інформацію через веб перед "
        "відповіддю. Віддавай пріоритет офіційним джерелам виробника, "
        "NHTSA/EPA та надійним автомобільним джерелам. "
        "Не називай приблизну батарею, двигун, коробку, роки випуску "
        "або потужність навмання. Якщо точна версія/ринок/рік критично "
        "впливає на відповідь — скажи про це або постав ОДНЕ уточнення. "
        "Якщо клієнт назвав неможливу комбінацію моделі та року — "
        "м'яко виправ її. "
        "НЕ використовуй Інтернет для тарифів Auction Auto, доставки, "
        "портів, комісії компанії або випадкової оцінки ціни авто. "
        "Ці бізнес-дані беруться тільки з внутрішньої бази."
    )

    domain_rule = (
        "КРИТИЧНО: ти працюєш ТІЛЬКИ як автомобільний консультант "
        "Auction Auto. Не давай рецептів, прогнозів погоди, порад "
        "по спорту, політиці, програмуванню чи інших сторонніх темах. "
        "Якщо тема не пов'язана з автомобілями або Auction Auto — "
        "коротко скажи, що спеціалізуєшся лише на авто, і поверни "
        "розмову до автомобільної консультації."
    )

    user_turns = sum(
        1
        for item in history
        if item.get("role") == "user"
    )

    selection_already_offered = state.get(
        "selection_offered",
        False,
    )

    selection_already_offered = state.get(
        "selection_offered",
        False,
    )

    selection_declined = state.get(
        "selection_declined",
        False,
    )

    lead_already_sent = state.get(
        "lead_sent",
        False,
    )

    lead_rule = f"""
ТВОЯ РОЛЬ — СПОЧАТКУ НОРМАЛЬНО КОНСУЛЬТУВАТИ КЛІЄНТА,
А ПОТІМ У ПРИРОДНИЙ МОМЕНТ М'ЯКО ЗАПРОПОНУВАТИ ПІДБІР.

СТАТУС ПЕРЕДАЧІ ЛІДА: {lead_already_sent}

ЯКЩО СТАТУС ПЕРЕДАЧІ ЛІДА = True:
- клієнт УЖЕ залишив контакт;
- менеджеру УЖЕ передано запит;
- НІКОЛИ більше не пропонуй підбір у цьому діалозі;
- НІКОЛИ більше не проси номер;
- не пиши "якщо хочете, можемо подивитися актуальні варіанти";
- просто продовжуй відповідати на будь-які автомобільні питання клієнта.

КІЛЬКІСТЬ УТОЧНЮЮЧИХ ПИТАНЬ НЕ ОБМЕЖЕНА.
НІКОЛИ не використовуй правило "після 2/3/5 повідомлень треба передати менеджеру".
Орієнтуйся тільки на зміст розмови.

==================================================
1. КОНСУЛЬТАЦІЯ
==================================================

Якщо клієнт цікавиться автомобілем, допоможи йому сформувати запит.

Можеш природно уточнювати:
- рік;
- бюджет;
- пробіг;
- комплектацію;
- двигун;
- привід;
- батарею;
- інші важливі побажання.

Але НЕ роби анкету.
Став тільки ті питання, які логічні в поточному контексті.
Зазвичай одне питання або один короткий блок за раз.

Якщо клієнт ставить конкретні питання про авто —
відповідай на них стільки, скільки потрібно.

Наприклад:
"Какая коробка?"
"Какой двигатель?"
"Что по надежности?"
"Какие комплектации?"
"Какой пробег лучше?"
"Сколько доставка?"
"Какая комиссия?"

На такі питання СПОЧАТКУ дай відповідь.
Не переводь кожну відповідь у продаж.
Не проси номер.

==================================================
2. КОЛИ М'ЯКО ЗАПРОПОНУВАТИ ПІДБІР
==================================================

Коли з розмови вже більш-менш зрозуміло,
яке авто і приблизно які параметри цікавлять клієнта,
у природний момент ненав'язливо запропонуй
подивитися актуальну підбірку варіантів.

ВАЖЛИВО:
це НЕ залежить від кількості повідомлень.
Іноді запит зрозумілий за 2 репліки.
Іноді потрібні 10+ повідомлень консультації.
Це нормально.

НЕ пропонуй підбір одразу після першої короткої фрази,
якщо запит ще майже не зрозумілий.

Хороша м'яка пропозиція:

"До речі, якщо хочете, можемо підібрати кілька актуальних
варіантів під ці параметри й показати, що зараз є на торгах."

Або російською:

"Кстати, если хотите, можем подобрать несколько актуальных
вариантов под эти параметры и посмотреть, что сейчас есть на торгах."

НЕ кажи одразу:
"Оставьте номер."
"Передаю менеджеру."
"Нужен телефон."

Спочатку тільки запитай, чи цікава клієнту підбірка.

Якщо ти зробила таку м'яку пропозицію,
ОБОВ'ЯЗКОВО додай в самому кінці службовий маркер:

<OFFER_SELECTION>

Клієнт цей маркер не побачить.

==================================================
3. ЯКЩО КЛІЄНТ ПОГОДИВСЯ
==================================================

Телефон самостійно НЕ проси.

Python побачить згоду клієнта після soft-offer
і сам попросить номер телефону для передачі менеджеру.

==================================================
4. ЯКЩО КЛІЄНТ НЕ ЗАЦІКАВИВСЯ ПІДБІРКОЮ
==================================================

Якщо клієнт відмовився або сказав, що поки просто цікавиться —
спокійно продовжуй консультацію.

Не завершуй діалог.
Не ображайся.
Не повторюй пропозицію підбірки через кожні кілька повідомлень.

Якщо клієнт уже відмовився від підбірки,
НЕ пропонуй її повторно самостійно,
доки клієнт явно не покаже новий інтерес до актуальних варіантів.

==================================================
5. ЯВНИЙ ЗАПИТ НА АКТУАЛЬНІ ВАРІАНТИ
==================================================

Якщо клієнт сам пише щось на кшталт:
"покажите варианты"
"что сейчас есть?"
"подберите"
"давайте искать"
"хочу посмотреть лоты"
"які є варіанти?"
"давайте підбір"

це вже явний сигнал на підбір.
Python окремо обробить такий запит.

==================================================
6. ЗМІШАНИЙ ЗАПИТ
==================================================

Якщо клієнт одночасно назвав авто і поставив питання,
СПОЧАТКУ відповідай на питання.

Приклад:
"Интересует BMW 540. Какая там коробка?"

Добре:
"На 540i встановлюється 8-ступінчастий автомат ZF.
Для B58 це дуже вдала зв'язка."

Після цього можеш продовжити консультацію.
Не обов'язково відразу пропонувати підбір.

==================================================
ГОЛОВНЕ
==================================================

Консультація може тривати скільки завгодно.
Немає ліміту на кількість питань.

Підбір пропонуй не "за таймером",
а коли це виглядає природним наступним кроком
і ти вже розумієш, що приблизно потрібно клієнту.

Чи зараз активна пропозиція підбірки: {selection_already_offered}
Чи клієнт раніше відмовився від підбірки: {selection_declined}

Якщо клієнт раніше відмовився від підбірки ({selection_declined}),
не пропонуй її повторно без явного нового інтересу клієнта.

Відповідай коротко й природно, зазвичай 1-3 речення.
Не вітайся повторно в середині діалогу.
"""

    if state["do_not_ask_phone"]:
        phone_rule = (
            "КРИТИЧНО: клієнт прямо "
            "попросив більше НЕ "
            "просити номер телефону. "
            "Не проси контакт у цьому "
            "діалозі, якщо клієнт сам "
            "не попросить зв'язати "
            "його з менеджером."
        )

    dialog_memory_context = (
        build_dialog_memory_context(
            user_id
        )
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "system",
            "content": dialog_memory_context,
        },
        {
            "role": "system",
            "content": (
                "ВНУТРІШНЯ ІНФОРМАЦІЯ "
                "AUCTION AUTO:\n\n"
                + COMPANY_INFO
            ),
        },
        {
            "role": "system",
            "content": (
                verified_context
            ),
        },
        {
            "role": "system",
            "content": (
                web_context
                if web_context
                else (
                    "WEB VERIFICATION DATA: "
                    "для цього повідомлення веб-перевірка не запускалась."
                )
            ),
        },
        {
            "role": "system",
            "content": web_rule,
        },
        {
            "role": "system",
            "content": phone_rule,
        },
        {
            "role": "system",
            "content": language_rule,
        },
        {
            "role": "system",
            "content": style_rule,
        },
        {
            "role": "system",
            "content": domain_rule,
        },
        {
            "role": "system",
            "content": price_rule,
        },
        {
            "role": "system",
            "content": lead_rule,
        },
    ] + history[-20:]

    if conflict_answer:
        answer = conflict_answer

        print(
            "WEB FACT CONFLICT:",
            answer,
        )

    else:
        answer = await consultant_chat(
            messages=messages,
            num_predict=260,
            temperature=0.15,
            use_browser_search=(
                groq_browser_needed
            ),
        )

    # Додатковий захист:
    # якщо клієнт заборонив номер,
    # а AI все одно його попросила —
    # генеруємо відповідь ще раз.
    if (
        state["do_not_ask_phone"]
        and ai_asks_for_phone(
            answer
        )
    ):
        correction_messages = (
            messages
            + [
                {
                    "role": "system",
                    "content": (
                        "Твоя попередня "
                        "відповідь порушила "
                        "правило: клієнт "
                        "заборонив просити "
                        "номер. Переформулюй "
                        "відповідь без "
                        "будь-якої згадки "
                        "про контакт, номер "
                        "або менеджера."
                    ),
                }
            ]
        )

        answer = await consultant_chat(
            messages=(
                correction_messages
            ),
            num_predict=180,
            temperature=0.1,
        )

    # ======================================
    # MEMORY GUARD
    # ======================================

    memory = get_dialog_memory(
        user_id
    )

    repeated_topics = (
        repeated_known_questions(
            answer,
            memory,
        )
    )

    # Якщо web вже зловив фактичну помилку,
    # не перезаписуємо цю відповідь Memory Guard'ом.
    if conflict_answer:
        repeated_topics = []

    if repeated_topics:
        print(
            "MEMORY GUARD: Qwen повторно питає:",
            repeated_topics,
        )

        # Якщо клієнт щойно дав коротку відповідь
        # на наше уточнення (X5 / 2016-2017 / до 100 тис.),
        # НЕ просимо Qwen "виправитися".
        # Python сам переходить до наступного невідомого параметра.
        user_is_short_answer = (
            "?" not in user_text
            and len(user_text.strip()) <= 100
        )

        if user_is_short_answer:
            answer = build_memory_fallback(
                user_id,
                current_language,
            )

            print(
                "MEMORY GUARD HARD FALLBACK:",
                answer,
            )

        else:
            # Якщо клієнт поставив реальне питання,
            # даємо Qwen одну контрольовану спробу
            # відповісти саме на нього без повторення відомих параметрів.
            correction = (
                "ТВОЯ ПОПЕРЕДНЯ ВІДПОВІДЬ ПОРУШИЛА ПАМ'ЯТЬ ДІАЛОГУ. "
                "Ти повторно запитав уже відомий параметр: "
                + ", ".join(repeated_topics)
                + ". "
                "Клієнт поставив або продовжив конкретне питання. "
                "Відповідай НА ЙОГО ПОТОЧНЕ ПОВІДОМЛЕННЯ. "
                "НЕ ПИТАЙ повторно відомі параметри. "
                "Не вітайся повторно. "
                "Не починай підбір автомобіля з нуля."
            )

            answer = await consultant_chat(
                messages=(
                    messages
                    + [
                        {
                            "role": "assistant",
                            "content": answer,
                        },
                        {
                            "role": "system",
                            "content": correction,
                        },
                    ]
                ),
                num_predict=180,
                temperature=0.1,
            )

            repeated_again = (
                repeated_known_questions(
                    answer,
                    memory,
                )
            )

            if repeated_again:
                print(
                    "MEMORY GUARD HARD FALLBACK AFTER RETRY:",
                    repeated_again,
                )

                answer = build_memory_fallback(
                    user_id,
                    current_language,
                )

    # Основний механізм — службовий маркер.
    # Додатково є страховка по тексту відповіді,
    # якщо маленька локальна модель забула маркер.
    has_offer_marker = (
        "<OFFER_SELECTION>"
        in answer
    )

    if has_offer_marker:
        answer = (
            answer.replace(
                "<OFFER_SELECTION>",
                "",
            ).strip()
        )

    if state.get(
        "lead_sent",
        False,
    ):
        # Контакт уже передано — будь-який випадковий
        # soft-offer від Qwen ігноруємо.
        state["selection_offered"] = False

    elif (
        has_offer_marker
        or answer_offers_manager_transfer(
            answer
        )
    ):
        state["selection_offered"] = True

    history.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )

    remember_assistant_questions(
        user_id,
        answer,
    )

    if len(history) > 30:
        chat_histories[user_id] = (
            history[-30:]
        )

    save_persistent_dialog_data()

    return answer


# ==========================================
# КАРТКА ЛІДА
# ==========================================

def dialogue_text(
    user_id: int,
):
    history = chat_histories.get(
        user_id,
        [],
    )

    lines = []

    for item in history:
        role = item.get("role")

        content = (
            item.get(
                "content",
                "",
            ).strip()
        )

        if not content:
            continue

        if role == "user":
            lines.append(
                f"Клієнт: {content}"
            )

        elif role == "assistant":
            lines.append(
                f"Консультант: "
                f"{content}"
            )

    return "\n".join(lines)


async def make_lead_summary(
    user_id: int,
):
    text = dialogue_text(
        user_id
    )

    if not text:
        return (
            "Авто: не вказано\n"
            "Модель: не вказано\n"
            "Рік: не вказано\n"
            "Бюджет: не вказано\n"
            "Пробіг: не вказано\n"
            "Комплектація: не вказано\n"
            "Двигун / батарея / привід: "
            "не вказано\n"
            "Побажання: не вказано"
        )

    messages = [
        {
            "role": "system",
            "content": SUMMARY_PROMPT,
        },
        {
            "role": "user",
            "content": text,
        },
    ]

    try:
        return await ollama_chat(
            messages=messages,
            num_predict=160,
            temperature=0.1,
        )

    except Exception as error:
        print(
            "Не вдалося зробити "
            f"підсумок: {error}"
        )

        return (
            "Не вдалося автоматично "
            "сформувати підсумок."
        )



def ensure_model_in_lead_summary(
    user_id: int,
    summary: str,
):
    """
    Гарантує окремий рядок "Модель:" у картці ліда.

    Основне джерело — структурована пам'ять Python,
    а не здогадки LLM.
    """

    memory = get_dialog_memory(
        user_id
    )

    models = memory.get(
        "model",
        [],
    )

    model = (
        models[-1]
        if models
        else "не вказано"
    )

    # Якщо модель уже є — підміняємо її
    # на значення зі структурованої пам'яті.
    if re.search(
        r"(?mi)^Модель\\s*:",
        summary,
    ):
        return re.sub(
            r"(?mi)^Модель\\s*:.*$",
            f"Модель: {model}",
            summary,
            count=1,
        )

    # Інакше вставляємо одразу після "Авто:".
    lines = summary.splitlines()

    result = []
    inserted = False

    for line in lines:
        result.append(line)

        if (
            not inserted
            and re.match(
                r"(?i)^Авто\\s*:",
                line.strip(),
            )
        ):
            result.append(
                f"Модель: {model}"
            )
            inserted = True

    if not inserted:
        result.insert(
            0,
            f"Модель: {model}",
        )

    return "\\n".join(
        result
    )


async def send_final_lead(
    message: Message,
    title: str,
    phone: str | None = None,
    force: bool = False,
):
    user_id = message.from_user.id

    state = get_state(
        user_id
    )

    if (
        state["lead_sent"]
        and not force
    ):
        return

    summary = (
        await make_lead_summary(
            user_id
        )
    )

    summary = ensure_model_in_lead_summary(
        user_id,
        summary,
    )

    text = (
        f"{title}\n\n"
        f"{user_info(message)}"
    )

    if phone:
        text += (
            f"\nТелефон: {phone}"
        )

    text += (
        f"\n\n{summary}"
    )

    await send_to_admin(
        message.bot,
        text,
    )

    state["lead_sent"] = True


# ==========================================
# TELEGRAM
# ==========================================

dp = Dispatcher()


@dp.message(
    Command("chatid")
)
async def chat_id_handler(
    message: Message,
):
    await message.answer(
        f"Chat ID:\n"
        f"{message.chat.id}"
    )


@dp.message(
    CommandStart()
)
async def start_handler(
    message: Message,
):
    if (
        message.chat.type
        != "private"
    ):
        return

    user_id = (
        message.from_user.id
    )

    greeting = (
        "Добрий день! 👋 "
        "Напишіть, яке авто "
        "Вас цікавить — "
        "допоможу зорієнтуватися."
    )

    reset_user_dialog(
        user_id,
        greeting=greeting,
    )

    await message.answer(
        greeting,
        reply_markup=main_keyboard,
    )


# ==========================================
# КОНТАКТ
# ==========================================

@dp.message(F.contact)
async def contact_handler(
    message: Message,
):
    if (
        message.chat.type
        != "private"
    ):
        return

    user_id = (
        message.from_user.id
    )

    state = get_state(
        user_id
    )

    if state["ended"]:
        await message.answer(
            "Цей діалог завершено. "
            "Натисніть "
            "«🔄 Почати новий чат», "
            "щоб продовжити.",
            reply_markup=main_keyboard,
        )
        return

    phone = (
        message.contact.phone_number
    )

    state["phone"] = phone
    state["waiting_for_phone"] = False
    state["selection_offered"] = False
    state["selection_declined"] = False

    await message.answer(
        "Дякую 👍 Передам Ваш "
        "контакт менеджеру. "
        "Він перегляне актуальні "
        "варіанти та зв'яжеться "
        "з Вами.",
        reply_markup=main_keyboard,
    )

    await send_final_lead(
        message=message,
        title="🔥 НОВИЙ ЛІД",
        phone=phone,
    )


# ==========================================
# ВИКЛИК МЕНЕДЖЕРА
# ==========================================

@dp.message(
    F.text
    == "👨‍💼 Виклик менеджера"
)
async def manager_handler(
    message: Message,
):
    if (
        message.chat.type
        != "private"
    ):
        return

    user_id = (
        message.from_user.id
    )

    state = get_state(
        user_id
    )

    if state["ended"]:
        await message.answer(
            "Цей діалог завершено. "
            "Натисніть "
            "«🔄 Почати новий чат», "
            "щоб продовжити.",
            reply_markup=main_keyboard,
        )
        return

    await send_final_lead(
        message=message,
        title=(
            "🚨 КЛІЄНТ ВИКЛИКАЄ "
            "МЕНЕДЖЕРА"
        ),
        phone=state["phone"],
        force=True,
    )

    if state["phone"]:
        await message.answer(
            "Добре 👍 Передав "
            "Ваш запит менеджеру.",
            reply_markup=main_keyboard,
        )

    else:
        state[
            "waiting_for_phone"
        ] = True

        await message.answer(
            "Добре 👍 Щоб менеджер "
            "міг зв'язатися з Вами, "
            "натисніть "
            "«📱 Поділитися номером».",
            reply_markup=main_keyboard,
        )


# ==========================================
# НОВИЙ ЧАТ
# ==========================================

@dp.message(
    F.text
    == "🔄 Почати новий чат"
)
async def new_chat_handler(
    message: Message,
):
    if (
        message.chat.type
        != "private"
    ):
        return

    user_id = (
        message.from_user.id
    )

    reset_user_dialog(
        user_id
    )

    await message.answer(
        "Добре 👍 Починаємо "
        "новий діалог. "
        "Напишіть, яке авто "
        "Вас цікавить.",
        reply_markup=main_keyboard,
    )


# ==========================================
# ЗАВЕРШИТИ ЧАТ
# ==========================================

@dp.message(
    F.text
    == "✅ Завершити чат"
)
async def finish_chat_handler(
    message: Message,
):
    if (
        message.chat.type
        != "private"
    ):
        return

    user_id = (
        message.from_user.id
    )

    state = get_state(
        user_id
    )

    state["ended"] = True
    state["waiting_for_phone"] = False

    await message.answer(
        "Дякую за звернення 👍 "
        "Якщо захочете продовжити — "
        "натисніть "
        "«🔄 Почати новий чат».",
        reply_markup=main_keyboard,
    )


# ==========================================
# ЗВИЧАЙНИЙ ТЕКСТ
# ==========================================

@dp.message(F.text)
async def message_handler(
    message: Message,
):
    if (
        message.chat.type
        != "private"
    ):
        return

    user_id = (
        message.from_user.id
    )

    user_text = (
        message.text.strip()
    )

    state = get_state(
        user_id
    )

    if state["ended"]:
        await message.answer(
            "Цей діалог завершено 👍 "
            "Натисніть "
            "«🔄 Почати новий чат», "
            "щоб продовжити.",
            reply_markup=main_keyboard,
        )
        return

    print(
        f"Клієнт {user_id}: "
        f"{user_text}"
    )

    # Оновлюємо мову діалогу.
    state["language"] = detect_message_language(
        user_text,
        previous=state.get(
            "language",
            "uk",
        ),
    )

    # Якщо перед цим бот попросив модель
    # саме для морського тарифу —
    # це повідомлення НЕ віддаємо
    # у звичайну консультацію Qwen.
    if state.get(
        "waiting_for_sea_vehicle",
        False,
    ):
        sea_answer = await answer_pending_sea_vehicle(
            user_id=user_id,
            vehicle_text=user_text,
        )

        if sea_answer:
            remember_manual_exchange(
                user_id=user_id,
                user_text=user_text,
                assistant_text=sea_answer,
            )

            print(
                f"SEA RATE: {sea_answer}"
            )

            await message.answer(
                sea_answer,
                reply_markup=main_keyboard,
            )

            return

    # Якщо лід уже передано, але клієнт хоче
    # поставити ще кілька питань — просто запрошуємо питати.
    if state.get(
        "lead_sent",
        False,
    ):
        lower_text = user_text.lower()

        continue_phrases = [
            "ще пару питань",
            "ще кілька питань",
            "ще декілька питань",
            "є ще питання",
            "можу ще спитати",
            "можна ще запитати",
            "можеш ще дати відповіді",
            "можете ще дати відповіді",
            "еще пару вопросов",
            "еще несколько вопросов",
            "есть еще вопросы",
            "можно еще спросить",
            "можешь еще ответить",
        ]

        if any(
            phrase in lower_text
            for phrase in continue_phrases
        ):
            answer = (
                "Звісно 👍 Питайте, що ще цікавить — "
                "продовжимо консультацію."
                if state.get("language") == "uk"
                else
                "Конечно 👍 Спрашивайте, что ещё интересно — "
                "продолжим консультацию."
            )

            remember_manual_exchange(
                user_id=user_id,
                user_text=user_text,
                assistant_text=answer,
            )

            await message.answer(
                answer,
                reply_markup=main_keyboard,
            )

            return

    # Клієнт попросив
    # не просити номер.
    if user_forbids_phone_request(
        user_text
    ):
        state[
            "do_not_ask_phone"
        ] = True

        state[
            "waiting_for_phone"
        ] = False

    # Якщо раніше бот уже запропонував підбір,
    # а клієнт погодився — Python сам просить контакт.
    if (
        state.get("selection_offered")
        and is_affirmative(user_text)
        and not state["waiting_for_phone"]
    ):
        state["selection_offered"] = False
        state["selection_declined"] = False

        if state["do_not_ask_phone"]:
            answer = (
                "Добре 👍 Можемо продовжити консультацію тут. "
                "Якщо самі захочете зв'язок із менеджером — скажіть."
                if state.get("language") == "uk"
                else
                "Хорошо 👍 Можем продолжить консультацию здесь. "
                "Если сами захотите связь с менеджером — скажите."
            )

            remember_manual_exchange(
                user_id=user_id,
                user_text=user_text,
                assistant_text=answer,
            )

            await message.answer(
                answer,
                reply_markup=main_keyboard,
            )
            return

        answer = ask_phone_for_lead_text(
            state.get(
                "language",
                "uk",
            )
        )

        state["waiting_for_phone"] = True

        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=answer,
        )

        await message.answer(
            answer,
            reply_markup=main_keyboard,
        )
        return

    if (
        state.get("selection_offered")
        and is_negative(user_text)
    ):
        state["selection_offered"] = False
        state["selection_declined"] = True

        answer = decline_selection_text(
            state.get(
                "language",
                "uk",
            )
        )

        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=answer,
        )

        await message.answer(
            answer,
            reply_markup=main_keyboard,
        )
        return

    # Якщо клієнт прямо сам просить підбір/актуальні варіанти —
    # не ганяємо його через зайві питання.
    if (
        explicitly_wants_selection(user_text)
        and not state["waiting_for_phone"]
    ):
        state["selection_declined"] = False
        if state["do_not_ask_phone"]:
            # Клієнт заборонив просити телефон —
            # поважаємо це.
            pass
        else:
            answer = ask_phone_for_lead_text(
                state.get(
                    "language",
                    "uk",
                )
            )

            state["waiting_for_phone"] = True
            state["selection_offered"] = False

            remember_manual_exchange(
                user_id=user_id,
                user_text=user_text,
                assistant_text=answer,
            )

            await message.answer(
                answer,
                reply_markup=main_keyboard,
            )
            return

    # Якщо бот чекає номер.
    if state["waiting_for_phone"]:

        if looks_like_phone(
            user_text
        ):
            state["phone"] = user_text
            state[
                "waiting_for_phone"
            ] = False

            chat_histories.setdefault(
                user_id,
                [],
            ).append(
                {
                    "role": "user",
                    "content": (
                        "Мій номер телефону: "
                        f"{user_text}"
                    ),
                }
            )

            await message.answer(
                "Дякую 👍 Передам "
                "Ваш контакт менеджеру.",
                reply_markup=main_keyboard,
            )

            await send_final_lead(
                message=message,
                title="🔥 НОВИЙ ЛІД",
                phone=user_text,
            )

            return

        if (
            not state[
                "do_not_ask_phone"
            ]
            and user_text.lower()
            in {
                "добре",
                "ок",
                "окей",
                "так",
                "звісно",
                "гаразд",
                "да",
                "хорошо",
            }
        ):
            await message.answer(
                "Надішліть, будь ласка, "
                "Ваш номер телефону або "
                "натисніть "
                "«📱 Поділитися номером».",
                reply_markup=main_keyboard,
            )

            return

    # ======================================
    # ПРЯМА ВІДПОВІДЬ ПО ВАРТОСТІ ПОСЛУГ
    # ======================================

    fee_answer = service_fee_answer(
        user_text=user_text,
        language=state.get(
            "language",
            "uk",
        ),
    )

    if fee_answer:
        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=fee_answer,
        )

        print(
            f"SERVICE FEE: {fee_answer}"
        )

        await message.answer(
            fee_answer,
            reply_markup=main_keyboard,
        )

        return

    # ======================================
    # SMART ВІДПОВІДЬ ПО ПРАЙСАХ
    # ======================================

    logistics_answer = await try_smart_logistics_answer(
        user_id=user_id,
        user_text=user_text,
    )

    # Старий обробник залишаємо як fallback
    # для рідкісних форматів запиту.
    if not logistics_answer:
        logistics_answer = await try_direct_logistics_answer(
            user_id=user_id,
            user_text=user_text,
        )

    if logistics_answer:
        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=logistics_answer,
        )

        print(
            f"LOGISTICS: {logistics_answer}"
        )

        await message.answer(
            logistics_answer,
            reply_markup=main_keyboard,
        )

        return

    # ======================================
    # PRICE GUARD: ЦІНА САМОГО АВТО
    # ======================================

    if is_vehicle_price_question(
        user_text
    ):
        price_answer = safe_vehicle_price_answer(
            state.get(
                "language",
                "uk",
            )
        )

        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=price_answer,
        )

        print(
            f"VEHICLE PRICE BLOCKED: "
            f"{user_text}"
        )

        await message.answer(
            price_answer,
            reply_markup=main_keyboard,
        )

        return

    # ======================================
    # DOMAIN GUARD
    # ======================================

    allowed = await is_allowed_domain(
        user_id=user_id,
        user_text=user_text,
    )

    if not allowed:
        off_topic_answer = get_offtopic_reply(
            state.get(
                "language",
                "uk",
            )
        )

        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=off_topic_answer,
        )

        print(
            f"OFFTOPIC BLOCKED: {user_text}"
        )

        await message.answer(
            off_topic_answer,
            reply_markup=main_keyboard,
        )

        return

    # ======================================
    # ДЕТЕРМІНОВАНЕ УТОЧНЕННЯ ЗАПИТУ
    # ======================================

    qualification_answer = await try_deterministic_qualification(
        user_id=user_id,
        user_text=user_text,
    )

    if qualification_answer:
        remember_manual_exchange(
            user_id=user_id,
            user_text=user_text,
            assistant_text=qualification_answer,
        )

        print(
            f"QUALIFICATION: {qualification_answer}"
        )

        await message.answer(
            qualification_answer,
            reply_markup=main_keyboard,
        )

        return

    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
    )

    try:
        answer = await ask_ollama(
            user_id=user_id,
            user_text=user_text,
        )

        # Жорстка страховка:
        # звичайна Qwen не має права сама називати гроші.
        answer = remove_unsupported_ai_price(
            answer,
            state.get(
                "language",
                "uk",
            ),
        )

        wrong_brand = (
            answer_mentions_wrong_vehicle_brand(
                user_id=user_id,
                user_text=user_text,
                answer=answer,
            )
        )

        if wrong_brand:
            memory = get_dialog_memory(
                user_id
            )

            current_vehicle = (
                build_current_vehicle_summary(
                    memory
                )
            )

            print(
                "VEHICLE CONTAMINATION GUARD:",
                wrong_brand,
                "| current:",
                current_vehicle,
            )

            memory_context = (
                build_dialog_memory_context(
                    user_id
                )
            )

            correction_messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "system",
                    "content": memory_context,
                },
                {
                    "role": "system",
                    "content": (
                        "ПОМИЛКА В ПОПЕРЕДНІЙ ВІДПОВІДІ: "
                        f"ти згадав {wrong_brand}, хоча поточний "
                        f"автомобіль клієнта: {current_vehicle}. "
                        "Відповідай ТІЛЬКИ про поточний автомобіль. "
                        "Не змінюй марку або модель. Якщо клієнт "
                        "поставив технічне питання — дай коротку "
                        "відповідь саме на нього."
                    ),
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ]

            answer = await consultant_chat(
                messages=correction_messages,
                num_predict=220,
                temperature=0.1,
                use_browser_search=(
                    is_web_technical_question(
                        user_text
                    )
                ),
            )

        print(
            f"AI: {answer}"
        )

        # Телефон контролює тільки Python lead-flow.
        # Якщо Qwen випадково попросила номер, ми НЕ вважаємо,
        # що бот тепер чекає телефон.

        await message.answer(
            answer,
            reply_markup=main_keyboard,
        )

    except (
        aiohttp.ClientConnectorError
    ):
        print(
            "ПОМИЛКА: "
            "Не вдалося підключитися "
            "до Ollama"
        )

        await message.answer(
            "Виникла технічна помилка. "
            "Спробуйте, будь ласка, "
            "трохи пізніше.",
            reply_markup=main_keyboard,
        )

    except Exception as error:
        print(
            f"ПОМИЛКА: {error}"
        )

        await message.answer(
            "Виникла технічна помилка. "
            "Спробуйте, будь ласка, "
            "трохи пізніше.",
            reply_markup=main_keyboard,
        )


# ==========================================
# ЗАПУСК
# ==========================================

async def main():
    bot = Bot(
        token=BOT_TOKEN
    )

    print(
        "Telegram AI Manager "
        "запущений..."
    )

    if GROQ_API_KEY:
        print(
            f"Main LLM: {GROQ_MODEL} via Groq"
        )
        print(
            "Groq Browser Search: ON for technical questions"
        )
        print(
            f"Fallback LLM: {OLLAMA_MODEL} via Ollama"
        )
    else:
        print(
            f"Main LLM: {OLLAMA_MODEL} via Ollama"
        )
        print(
            "Groq: OFF (немає GROQ_API_KEY)"
        )

    if TAVILY_API_KEY:
        print(
            "Web verification: Tavily ON"
        )
    else:
        print(
            "Web verification: Tavily OFF "
            "(немає TAVILY_API_KEY)"
        )

    print(
        "System prompt:",
        SYSTEM_PROMPT_FILE,
    )

    print(
        "Company info:",
        COMPANY_INFO_FILE,
    )

    if ADMIN_CHAT_ID:
        print(
            f"Admin chat: "
            f"{ADMIN_CHAT_ID}"
        )

    else:
        print(
            "ADMIN_CHAT_ID "
            "ще не налаштований"
        )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )
