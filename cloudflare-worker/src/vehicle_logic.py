import re
from difflib import get_close_matches

from config import BRAND_ALIASES, REQUIRED_FIELDS
from name_catalog import resolve_brand, resolve_model
from utils import detect_language, normalize


NO_PREFERENCE = {
    "не знаю", "неважливо", "не важливо", "без різниці", "будь-який",
    "будь яка", "будь-яка", "любой", "любая", "без разницы", "не принципиально",
    "не принципово", "не имеет значения", "немає значення",
}

QUESTION_STARTS = (
    "який ", "яка ", "яке ", "які ", "скільки ", "що ", "чим ", "чому ",
    "коли ", "де ", "чи ", "какой ", "какая ", "какое ", "какие ",
    "сколько ", "что ", "чем ", "почему ", "когда ", "где ", "есть ли ",
    "what ", "which ", "how ",
)

CONSULT_WORDS = (
    "комплектац", "trim", "двигун", "двигатель", "engine", "мотор",
    "короб", "transmission", "cvt", "автомат", "батар", "kwh", "квт",
    "потуж", "мощност", "horsepower", "привід", "привод", "awd", "rwd",
    "fwd", "4wd", "запас ходу", "range", "розгін", "разгон", "0-100",
    "0-60", "надійн", "надежн", "ресурс", "проблем", "болячк", "слабк",
    "різниц", "разниц", "відрізня", "отлича", "рестайл", "поколін",
    "поколен", "роки випуску", "годы выпуска", "який кузов", "какой кузов",
)


# Canonical catalog aliases. Expand with frequently observed client spellings.
MODEL_ALIASES = {
    "Toyota": {
        "Sequoia": ("sequoia", "секвоя", "секвойя", "сиквоя", "сіквоя", "секвоія", "секвояа", "секвиа", "секвойа", "sekvoya", "seqouia", "secoia", "sequoya"),
        "Camry": ("camry", "камрі", "камри", "кемрі", "кемри", "kamri", "camri"),
        "RAV4": ("rav4", "rav 4", "рав4", "рав 4", "раф4", "раф 4"),
        "Highlander": ("highlander", "хайлендер", "хайландер", "haighlander"),
        "Corolla": ("corolla", "королла", "корола", "karolla"),
        "Prius": ("prius", "пріус", "приус"),
        "4Runner": ("4runner", "4 runner", "форранер", "форанер", "фор ранер"),
        "Tacoma": ("tacoma", "такома"),
        "Tundra": ("tundra", "тундра"),
        "Land Cruiser": ("land cruiser", "ленд крузер", "ланд крузер", "крузак"),
    },
    "Range Rover": {
        "Evoque": ("evoque", "евок", "евоук", "эвок", "евокью"),
        "Sport": ("sport", "спорт"),
        "Velar": ("velar", "велар"),
    },
    "Ford": {
        "F-150": ("f150", "ф150", "ф 150", "форд ф150", "еф150", "еф 150", "форд ф 150", "f 150"),
        "F-150 Lightning": ("f150 lightning", "f-150 lightning", "ф150 лайтнінг", "ф150 лайтнинг", "форд лайтнінг", "лайтнінг", "лайтнинг"),
        "Edge": ("edge", "едж", "эдж", "едже"),
        "Escape": ("escape", "ескейп", "эскейп", "ескап"),
        "Explorer": ("explorer", "експлорер", "эксплорер"),
        "Fusion": ("fusion", "фюжн", "фьюжн", "фужн"),
        "Mustang": ("mustang", "мустанг", "мастанг"),
    },
    "Nissan": {
        "Rogue": ("rogue", "роуг", "рог", "роґ"),
        "Leaf": ("leaf", "ліф", "лиф"),
        "Kicks": ("kicks", "кікс", "кикс"),
        "Ariya": ("ariya", "арія", "ария"),
    },
    "Hyundai": {
        "Tucson": ("tucson", "туссан", "тусан", "туксон", "туксoн"),
        "Santa Fe": ("santa fe", "санта фе", "сантафе"),
        "Kona": ("kona", "кона"),
        "Ioniq 5": ("ioniq 5", "іонік 5", "ионик 5", "айонік 5"),
    },
    "Kia": {
        "Sportage": ("sportage", "спортейдж", "спортаж", "спортадж"),
        "Sorento": ("sorento", "соренто"),
        "Niro": ("niro", "ніро", "ниро"),
        "EV6": ("ev6", "ev 6", "іві6", "ев6"),
    },
    "Subaru": {
        "Forester": ("forester", "форестер", "форєстер"),
        "Crosstrek": ("crosstrek", "крострек", "кросстрек", "крос трек"),
        "Outback": ("outback", "аутбек", "оутбек"),
    },
    "Tesla": {
        "Cybertruck": ("cybertruck", "кібертрак", "кибертрак", "сайбертрак", "сайбертрак", "кібертрук", "кибертрук", "cyber truck", "kibertrak", "kibertruck"),
        "Model 3": ("model 3", "модель 3", "модел 3"),
        "Model Y": ("model y", "модель у", "модель y", "модел у"),
        "Model S": ("model s", "модель с", "модель s", "модел с", "модел s", "модель ес", "model c"),
        "Model X": ("model x", "модель х", "модель x"),
    },
    "Chevrolet": {
        "Bolt EV": ("bolt ev", "болт ев", "болт ev"),
        "Equinox": ("equinox", "еквінокс", "эквинокс"),
        "Tahoe": ("tahoe", "тахо", "таго"),
    },
    "BMW": {
        "X3": ("x3", "х3", "ікс3", "икс3"),
        "X5": ("x5", "х5", "ікс5", "икс5"),
        "X6": ("x6", "х6", "ікс6", "икс6"),
    },
}

EXTRA_BRAND_ALIASES = {
    "тайота": "Toyota", "таёта": "Toyota", "тоёта": "Toyota",
    "toyta": "Toyota", "toyotaa": "Toyota", "toiyota": "Toyota",
    "субару": "Subaru", "субаруy": "Subaru",
    "хюндай": "Hyundai", "хундай": "Hyundai",
    "шеві": "Chevrolet", "шеви": "Chevrolet",
    "ренж ровер": "Range Rover", "рейндж ровер": "Range Rover",
    "рендж ровер": "Range Rover", "рейнджровер": "Range Rover",
}

def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9а-яіїєґё]+", "", normalize(value).casefold())


def canonical_model(brand: str, raw_model: str):
    resolved = resolve_model(brand, raw_model) if brand else None
    if resolved:
        return resolved
    catalog = MODEL_ALIASES.get(brand, {})
    key = _name_key(raw_model)
    if not key:
        return None
    aliases = {}
    for model, variants in catalog.items():
        for variant in (model, *variants):
            aliases[_name_key(variant)] = model
    if key in aliases:
        return aliases[key]
    # Correct isolated, near-exact misspellings only. Do not silently turn
    # an unknown model into an unrelated model.
    if len(key) >= 5:
        matches = get_close_matches(key, list(aliases), n=2, cutoff=0.86)
        if len(matches) == 1:
            return aliases[matches[0]]
    return None


def new_memory() -> dict:
    return {
        "brand": None,
        "model": None,
        "year": None,
        "year_preference": None,
        "mileage": None,
        "mileage_pending": None,
        "trim": None,
        "budget": None,
        "engine": None,
        "drive": None,
        "battery": None,
        "color": None,
        "body_type": None,
        "language": "uk",
        "last_question_topic": None,
        "preferences": [],
        "client_facts": [],
        "logistics_location": None,
    }


def normalize_memory(memory: dict | None) -> dict:
    result = new_memory()
    result.update(memory or {})

    # Migration from older cloud/local structures.
    if not result.get("year"):
        years = result.get("years")
        if isinstance(years, list) and years:
            result["year"] = "-".join(str(x) for x in years)
        elif years:
            result["year"] = str(years)

    result.pop("years", None)
    if result.get("brand") and result.get("model"):
        resolved = canonical_model(result["brand"], str(result["model"]))
        if resolved:
            result["model"] = resolved

    if not isinstance(result.get("preferences"), list):
        result["preferences"] = []
    if not isinstance(result.get("client_facts"), list):
        result["client_facts"] = []

    return result


def detect_brand(text: str):
    catalog_match = resolve_brand(text)
    if catalog_match:
        return catalog_match
    low = normalize(text).lower()
    aliases = {**BRAND_ALIASES, **EXTRA_BRAND_ALIASES}
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"(?<![\\w]){re.escape(alias)}(?![\\w])", low, flags=re.IGNORECASE):
            return aliases[alias]
    # Typo correction only for a single plausible brand token.
    for token in re.findall(r"[^\\W_]+", low, flags=re.UNICODE):
        if len(token) < 5:
            continue
        candidates = [a for a in aliases if " " not in a and len(a) >= 5]
        found = get_close_matches(token, candidates, n=2, cutoff=0.88)
        if len(found) == 1:
            return aliases[found[0]]
    return None


def is_question(text: str) -> bool:
    clean = normalize(text)
    low = clean.lower()

    if "?" in clean:
        return True

    if any(low.startswith(prefix) for prefix in QUESTION_STARTS):
        return True

    # Plain answers and requested vehicle configurations are not consultations.
    if re.match(r"(?i)^(?:максимальн|топов|базов|повн|найбільш|самая|самый|найкращ|хочу\\s+)(?:\\w|\\s)*", low) and "?" not in low:
        return False
    if "?" not in low and any(x in low for x in ("максимальна батарея", "найбільша батарея", "батарея на", "акумулятор на")):
        return False
    # Answers about preferred model years are not factual consultation questions.
    if is_relative_year_preference(clean):
        return False

    # A bare vehicle name must never be treated as a technical question.
    # In particular, 'Range Rover' contains 'range' (English for driving range).
    # Require an actual question form for English short keywords such as range/trim.
    if any(word in low for word in CONSULT_WORDS if word not in ("range", "trim")):
        return True

    return False


def is_consultation_question(text: str) -> bool:
    return is_question(text) and any(
        word in normalize(text).lower()
        for word in CONSULT_WORDS
    )


def is_factual_vehicle_question(text: str) -> bool:
    low = normalize(text).lower()
    factual = (
        "комплектац", "trim", "двигун", "двигатель", "engine", "мотор",
        "короб", "transmission", "cvt", "автомат", "батар", "kwh", "квт",
        "потуж", "мощност", "horsepower", "привід", "привод", "awd", "rwd",
        "fwd", "4wd", "запас ходу", "range", "розгін", "разгон", "0-100",
        "0-60", "роки випуску", "годы выпуска", "рестайл", "поколін",
        "поколен", "який кузов", "какой кузов",
    )
    return is_question(text) and any(word in low for word in factual)


def _remove_brand_aliases(text: str, brand: str | None) -> str:
    result = text
    if not brand:
        return result

    for alias, canonical in sorted(
        {**BRAND_ALIASES, **EXTRA_BRAND_ALIASES}.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if canonical != brand:
            continue
        result = re.sub(
            rf"(?<![\w]){re.escape(alias)}(?![\w])",
            " ",
            result,
            flags=re.IGNORECASE,
        )

    return normalize(result)


def _strip_intro(text: str) -> str:
    result = normalize(text)
    result = re.sub(
        r"(?i)^(?:"
        r"мене\s+цікавить|меня\s+интересует|"
        r"цікавить|интересует|"
        r"хочу|шукаю|ищу|"
        r"автомобіль|автомобиль|машина|модель"
        r")\s*[,;:\-]?\s*",
        "",
        result,
    )
    return normalize(result)


def is_relative_year_preference(text: str) -> bool:
    low = normalize(text).lower()
    if "?" in low:
        return False
    return bool(re.fullmatch(
        r"(?:за\\s+)?(?:останні|последние|найновіші|найновіших|свіжі|свежие|"
        r"новіші|нові|новые|найсвіжіші|самі\\s+нові|самые\\s+новые)"
        r"(?:\\s+(?:роки|років|года|годы|рік|год))?"
        r"(?:\\s+(?:випуску|выпуска|виробництва|производства))?",
        low,
    ))


def parse_year(text: str):
    clean = normalize(text)

    plus = re.search(r"\b((?:19[8-9]\d|20[0-3]\d))\s*\+", clean)
    if plus:
        return f"{plus.group(1)}+"

    rng = re.search(
        r"\b((?:19[8-9]\d|20[0-3]\d))\s*[-–—/]\s*((?:19[8-9]\d|20[0-3]\d))\b",
        clean,
    )
    if rng:
        return f"{rng.group(1)}-{rng.group(2)}"

    one = re.search(r"\b(?:19[8-9]\d|20[0-3]\d)\b", clean)
    if one:
        return one.group(0)

    return None


def parse_mileage(text: str, expected: bool = False):
    clean = normalize(text)
    low = clean.lower()
    if expected and low in NO_PREFERENCE:
        return "без обмежень"
    if not expected and not any(x in low for x in ("км", "миль", "mile", "пробіг", "пробег")):
        return None
    match = re.fullmatch(
        r"(?i)(до\s*)?(\d{1,3}(?:[ .]\d{3})+|\d{1,6})\s*"
        r"(тис\.?|тисяч\w*|тыс\.?|k)?\s*"
        r"(км|кілометр\w*|километр\w*|миль|милі|миля|miles?|mi)?",
        clean,
    )
    if not match or not match.group(4):
        return None
    number = int(match.group(2).replace(" ", "").replace(".", ""))
    if match.group(3):
        number *= 1000
    raw_unit = match.group(4).lower()
    unit = "миль" if raw_unit in ("миль", "милі", "миля", "mile", "miles", "mi") else "км"
    return ("до " if match.group(1) else "") + str(number) + " " + unit


def mileage_clarification(text: str):
    return bool(re.fullmatch(
        r"(?i)(до\s*)?\d{1,6}\s*(тис\.?|тисяч\w*|тыс\.?|k)?",
        normalize(text),
    ))


def resolve_pending_mileage(pending: str, reply: str):
    low = normalize(reply).lower()
    if low in NO_PREFERENCE:
        return "без обмежень"
    if mileage_clarification(low):
        return None
    m = re.search(r"\d{1,6}", pending)
    if not m:
        return None
    number = int(m.group())
    thousand = bool(re.search(r"тис|тыс|k", pending))
    if re.search(r"тис|тыс|тисяч|тысяч", low):
        thousand = True
    elif re.search(r"буквально|лише|всього|только", low):
        thousand = False
    elif not thousand and re.search(r"\b100\s*(?:км|миль|милі|mi)\b", low):
        thousand = False
    elif not thousand:
        return None
    unit = "миль" if re.search(r"миль|милі|миля|miles?|\bmi\b", low) else (
        "км" if re.search(r"км|кілометр|километр", low) else None
    )
    if not unit:
        return None
    return ("до " if pending.startswith("до ") else "") + str(number * (1000 if thousand else 1)) + " " + unit


def parse_drive(text: str):
    low = normalize(text).lower()
    if any(x in low for x in ("повний привід", "полный привод", "awd", "xdrive", "4wd", "quattro", "4matic")):
        return "AWD"
    if any(x in low for x in ("задній привід", "задний привод", "rwd")):
        return "RWD"
    if any(x in low for x in ("передній привід", "передний привод", "fwd")):
        return "FWD"
    return None


def parse_budget(text: str):
    clean = normalize(text)
    low = clean.lower()

    if not any(x in low for x in ("$", "usd", "дол", "бюдж", "під ключ", "под ключ")):
        return None

    match = re.search(
        r"(?i)(?:\$\s*)?(\d{1,3}(?:[ .]\d{3})+|\d{4,6})\s*(?:\$|usd|дол(?:ар(?:ів|ов)?)?)?",
        clean,
    )
    if not match:
        return clean[:100]

    number = match.group(1).replace(" ", "").replace(".", "")
    suffix = " під ключ" if "під ключ" in low else (" под ключ" if "под ключ" in low else "")
    return f"${number}{suffix}"


def _clean_model_candidate(text: str, brand: str | None):
    clean = _strip_intro(text)
    clean = _remove_brand_aliases(clean, brand)

    # Cut everything after clearly separate qualification details.
    cut = re.search(
        r"(?i)(?:"
        r"\b(?:19[8-9]\d|20[0-3]\d)\b|"
        r"\bдо\s+\d|"
        r"\b\d{3,6}\s*(?:км|миль|mi|miles)\b|"
        r"\b(?:повний|полный|передній|передний|задній|задний)\s+прив|"
        r"\b(?:awd|rwd|fwd|4wd|xdrive|quattro|4matic)\b|"
        r"\b(?:бюджет|budget)\b"
        r")",
        clean,
    )
    if cut:
        clean = clean[:cut.start()]

    clean = clean.strip(" ,.!?:;-/")
    clean = normalize(clean)

    if not clean or len(clean) > 70 or len(clean.split()) > 5:
        return None

    if clean.lower() in NO_PREFERENCE:
        return None

    if not re.search(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9]", clean):
        return None

    return clean


def parse_trim(text: str, expected: bool = False):
    clean = normalize(text)
    low = clean.lower()

    if expected:
        if low in NO_PREFERENCE:
            return "без конкретних побажань"
        if any(x in low for x in ("максимальн", "максимум", "найбільш", "топов", "базов")) and not is_question(clean):
            return clean[:100]
        if not is_question(clean) and len(clean) <= 100:
            return clean
        return None

    markers = (
        "максим", "топ", "предтоп", "пред-топ", "base", "базов",
        "limited", "premium", "sport", "performance", "platinum",
        "lariat", "sel", "xle", "xse", "touring", "luxury", "prestige",
        "gt-line", "gt line", "wind", "wave", "ultimate",
    )
    if any(x in low for x in markers) and not is_question(clean):
        return clean[:100]

    return None


def parse_engine(text: str):
    low = normalize(text).lower()
    if any(x in low for x in ("двигун", "двигатель", "мотор", "бензин", "дизел", "гібрид", "гибрид", "v6", "v8", "i4", "i6")):
        return normalize(text)[:120]
    return None


def parse_battery(text: str):
    low = normalize(text).lower()
    if any(x in low for x in ("батар", "kwh", "квт", "квт·год", "квтч")):
        return normalize(text)[:120]
    return None


def parse_color(text: str, expected: bool = False):
    if not expected:
        return None
    clean = normalize(text)
    if clean and not is_question(clean) and len(clean) <= 50:
        return clean
    return None


def extract_deterministic(memory: dict, text: str):
    result = normalize_memory(memory)
    before = dict(result)
    clean = normalize(text)

    result["language"] = detect_language(
        clean,
        fallback=result.get("language") or "uk",
    )

    expected = result.get("last_question_topic")

    brand = detect_brand(clean)
    if brand:
        result["brand"] = brand

    model = None
    if expected == "model" and not is_question(clean):
        model = _clean_model_candidate(clean, result.get("brand"))
    elif brand and not is_question(clean):
        model = _clean_model_candidate(clean, brand)
    elif result.get("brand") and not result.get("model") and not is_question(clean):
        model = _clean_model_candidate(clean, result.get("brand"))

    if model:
        recognized = canonical_model(result.get("brand"), model)
        if recognized:
            result["model"] = recognized
        elif result.get("brand"):
            # Let the semantic extractor handle unknown names instead of
            # saving 'купити Кібертрак' as a made-up model.
            result["model"] = model if len(model.split()) <= 2 and not re.match(
                r"(?i)^(купити|купить|придбати|приобрести|замовити|заказать)\\b", model
            ) else result.get("model")
    elif brand and not is_question(clean):
        recognized = resolve_model(brand, clean)
        if recognized:
            result["model"] = recognized

    year = parse_year(clean)
    if year:
        result["year"] = year
    elif expected == "year" and clean.lower() in NO_PREFERENCE:
        result["year"] = "без конкретного року"
    elif expected == "year" and is_relative_year_preference(clean):
        result["year"] = "останні роки випуску"
        result["year_preference"] = "latest"

    if result.get("mileage_pending"):
        mileage = parse_mileage(clean, expected=True) or resolve_pending_mileage(result["mileage_pending"], clean)
        if mileage:
            result["mileage"] = mileage
            result["mileage_pending"] = None
    else:
        mileage = parse_mileage(clean, expected=(expected == "mileage"))
        if mileage:
            result["mileage"] = mileage
        elif expected == "mileage" and mileage_clarification(clean):
            result["mileage_pending"] = clean
            result["mileage"] = None

    # Never treat subsequent free text as a trim while mileage clarification is active.
    trim = parse_trim(clean, expected=(expected == "trim" and not result.get("mileage_pending")))
    if trim:
        result["trim"] = trim

    budget = parse_budget(clean)
    if budget:
        result["budget"] = budget

    drive = parse_drive(clean)
    if drive:
        result["drive"] = drive

    engine = parse_engine(clean)
    if engine and not is_question(clean):
        result["engine"] = engine

    battery = parse_battery(clean)
    if battery and not is_question(clean):
        result["battery"] = battery

    color = parse_color(clean, expected=(expected == "color"))
    if color:
        result["color"] = color

    if clean:
        facts = list(result.get("client_facts") or [])
        if clean not in facts:
            facts.append(clean)
        result["client_facts"] = facts[-12:]

    changed = {
        key
        for key in result
        if result.get(key) != before.get(key)
    }

    return result, changed


def merge_ai_slots(memory: dict, slots: dict):
    result = normalize_memory(memory)
    changed = set()

    allowed = (
        "brand", "model", "year", "mileage", "trim", "budget",
        "engine", "drive", "battery", "color",
    )

    for key in allowed:
        value = slots.get(key)
        if value is None:
            continue

        value = normalize(value)
        if not value:
            continue

        # AI extraction is a fallback. Do not overwrite an already confirmed
        # required slot unless it was still missing.
        if key in REQUIRED_FIELDS and result.get(key):
            continue

        if result.get(key) != value:
            if key == "model":
                value = canonical_model(result.get("brand"), value) or value
            result[key] = value
            changed.add(key)

    return result, changed


def should_try_ai_extractor(memory: dict, text: str, changed: set) -> bool:
    clean = normalize(text)
    if not clean:
        return False

    result = normalize_memory(memory)

    # Direct question about a new/unknown car, e.g. "Что скажешь про Cupra Formentor?"
    # Use semantic extraction so we are not limited by a hardcoded brand list.
    if is_question(clean):
        return (
            not result.get("brand")
            or not result.get("model")
            or bool(detect_brand(clean))
        )
    expected = result.get("last_question_topic")
    if result.get("mileage_pending") or expected == "mileage":
        return False

    if expected in REQUIRED_FIELDS and expected not in changed and not result.get(expected):
        return True

    if not result.get("brand") or not result.get("model"):
        return True

    trim_hints = (
        "performance", "limited", "premium", "platinum", "lariat",
        "gt-line", "sport", "touring", "luxury", "prestige", "ultimate",
    )
    return any(hint in clean.lower() for hint in trim_hints)


def missing_required(memory: dict):
    data = normalize_memory(memory)
    return [field for field in REQUIRED_FIELDS if not data.get(field)]


def qualification_ready(memory: dict) -> bool:
    return not missing_required(memory) and not normalize_memory(memory).get("mileage_pending")


def vehicle_label(memory: dict) -> str:
    data = normalize_memory(memory)
    parts = [data.get("brand"), data.get("model"), data.get("year")]
    return " ".join(str(x) for x in parts if x).strip()


def next_question(memory: dict):
    data = normalize_memory(memory)
    lang = data.get("language") or "uk"

    if not data.get("brand"):
        return (
            "brand",
            "Яка марка авто Вас цікавить?"
            if lang == "uk"
            else "Какая марка автомобиля Вас интересует?",
        )

    if not data.get("model"):
        return (
            "model",
            f"Яка саме модель {data['brand']} Вас цікавить?"
            if lang == "uk"
            else f"Какая именно модель {data['brand']} Вас интересует?",
        )

    if not data.get("year"):
        return (
            "year",
            f"Добре, {data['brand']} {data['model']}. Який рік або діапазон років розглядаєте?"
            if lang == "uk"
            else f"Хорошо, {data['brand']} {data['model']}. Какой год или диапазон лет рассматриваете?",
        )

    if data.get("mileage_pending") and not data.get("mileage"):
        amount = data["mileage_pending"]
        return (
            "mileage",
            ("Уточніть, будь ласка, що означає «" + amount + "»: кілометри, тисячі кілометрів чи тисячі миль?")
            if lang == "uk"
            else ("Уточните, пожалуйста, что означает «" + amount + "»: километры, тысячи километров или тысячи миль?"),
        )

    if not data.get("mileage"):
        return (
            "mileage",
            f"Добре, орієнтуємося на {vehicle_label(data)}. По пробігу є побажання?"
            if lang == "uk"
            else f"Хорошо, ориентируемся на {vehicle_label(data)}. По пробегу есть пожелания?",
        )

    if not data.get("trim"):
        return (
            "trim",
            f"Добре, {vehicle_label(data)}, пробіг {data['mileage']}. По комплектації є побажання?"
            if lang == "uk"
            else f"Хорошо, {vehicle_label(data)}, пробег {data['mileage']}. По комплектации есть пожелания?",
        )

    return (None, None)


def selection_offer(memory: dict) -> str:
    lang = normalize_memory(memory).get("language") or "uk"

    if lang == "ru":
        return (
            "Если хотите, можем подобрать несколько актуальных вариантов "
            "под эти параметры и показать, что сейчас есть на торгах. Интересно?"
        )

    return (
        "Якщо хочете, можемо підібрати кілька актуальних варіантів "
        "під ці параметри й показати, що зараз є на торгах. Цікаво?"
    )


def phone_request(memory: dict) -> str:
    lang = normalize_memory(memory).get("language") or "uk"

    if lang == "ru":
        return (
            "Хорошо 👍 Оставьте номер телефона или нажмите «📱 Поділитися номером» — "
            "передам запрос менеджеру на подбор актуальных вариантов."
        )

    return (
        "Добре 👍 Залиште номер телефону або натисніть «📱 Поділитися номером» — "
        "передам запит менеджеру на підбір актуальних варіантів."
    )


def no_phone_request(text: str) -> bool:
    low = normalize(text).lower()
    return any(
        phrase in low
        for phrase in (
            "не проси номер", "не просіть номер", "не просите номер",
            "номер не дам", "не дам номер", "не хочу давати номер",
            "не хочу давать номер",
        )
    )


def explicit_selection_intent(text: str) -> bool:
    low = normalize(text).lower()

    if low in {
        "пригін під ключ",
        "пригон під ключ",
        "пригон под ключ",
        "хочу пригін під ключ",
        "хочу пригон под ключ",
        "хочу пригон під ключ",
    }:
        return True

    phrases = (
        "подбери варианты", "подберите варианты", "покажи варианты",
        "покажите варианты", "хочу варианты", "хочу подобрать",
        "хочу підбір", "підбери варіанти", "підберіть варіанти",
        "покажи варіанти", "покажіть варіанти", "актуальные лоты",
        "актуальні лоти", "актуальные варианты", "актуальні варіанти",
        "хочу заказать", "хочу замовити", "замовити авто", "заказать авто",
        "готов покупать", "готов купувати", "свяжите с менеджером",
        "зв'яжіть з менеджером", "вызов менеджера", "виклик менеджера",
    )
    return any(phrase in low for phrase in phrases)
