PRIMARY_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "openai/gpt-oss-20b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

REQUIRED_FIELDS = ("brand", "model", "year", "mileage", "trim")

BRAND_ALIASES = {
    "mercedes benz": "Mercedes-Benz", "mercedes-benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz", "мерседес": "Mercedes-Benz",
    "мерседес бенц": "Mercedes-Benz", "мерседес-бенц": "Mercedes-Benz",
    "bmw": "BMW", "бмв": "BMW",
    "audi": "Audi", "ауди": "Audi", "ауді": "Audi",
    "volkswagen": "Volkswagen", "vw": "Volkswagen", "фольксваген": "Volkswagen",
    "toyota": "Toyota", "тойота": "Toyota",
    "lexus": "Lexus", "лексус": "Lexus",
    "ford": "Ford", "форд": "Ford",
    "chevrolet": "Chevrolet", "chevy": "Chevrolet", "шевроле": "Chevrolet",
    "gmc": "GMC",
    "buick": "Buick", "бьюик": "Buick", "б'юїк": "Buick",
    "jeep": "Jeep", "джип": "Jeep",
    "dodge": "Dodge", "додж": "Dodge",
    "ram": "RAM",
    "chrysler": "Chrysler", "крайслер": "Chrysler",
    "nissan": "Nissan", "ниссан": "Nissan", "ніссан": "Nissan",
    "infiniti": "Infiniti", "инфинити": "Infiniti", "інфініті": "Infiniti",
    "acura": "Acura", "акура": "Acura",
    "honda": "Honda", "хонда": "Honda",
    "kia": "Kia", "киа": "Kia", "кіа": "Kia",
    "hyundai": "Hyundai", "хюндай": "Hyundai", "хендай": "Hyundai", "хундай": "Hyundai",
    "genesis": "Genesis", "генезис": "Genesis",
    "mazda": "Mazda", "мазда": "Mazda",
    "subaru": "Subaru", "субару": "Subaru",
    "mitsubishi": "Mitsubishi", "мицубиси": "Mitsubishi", "міцубісі": "Mitsubishi",
    "suzuki": "Suzuki", "сузуки": "Suzuki",
    "isuzu": "Isuzu", "исузу": "Isuzu", "ісузу": "Isuzu",
    "tesla": "Tesla", "тесла": "Tesla",
    "rivian": "Rivian", "ривиан": "Rivian", "рівіан": "Rivian",
    "lucid": "Lucid", "люсид": "Lucid", "люсід": "Lucid",
    "fisker": "Fisker", "фискер": "Fisker", "фіскер": "Fisker",
    "polestar": "Polestar", "полестар": "Polestar",
    "vinfast": "VinFast", "винфаст": "VinFast", "вінфаст": "VinFast",
    "porsche": "Porsche", "порше": "Porsche",
    "volvo": "Volvo", "вольво": "Volvo",
    "cadillac": "Cadillac", "кадиллак": "Cadillac", "каділак": "Cadillac",
    "lincoln": "Lincoln", "линкольн": "Lincoln", "лінкольн": "Lincoln",
    "land rover": "Land Rover", "ленд ровер": "Land Rover",
    "range rover": "Range Rover", "рендж ровер": "Range Rover",
    "jaguar": "Jaguar", "ягуар": "Jaguar",
    "mini": "MINI", "мини": "MINI", "міні": "MINI",
    "alfa romeo": "Alfa Romeo", "альфа ромео": "Alfa Romeo",
    "fiat": "Fiat", "фиат": "Fiat", "фіат": "Fiat",
    "maserati": "Maserati", "мазерати": "Maserati",
    "bentley": "Bentley", "бентли": "Bentley", "бентлі": "Bentley",
    "rolls-royce": "Rolls-Royce", "rolls royce": "Rolls-Royce", "роллс ройс": "Rolls-Royce",
    "lamborghini": "Lamborghini", "ламборгини": "Lamborghini", "ламборгіні": "Lamborghini",
    "ferrari": "Ferrari", "феррари": "Ferrari", "феррарі": "Ferrari",
    "smart": "Smart", "смарт": "Smart",
    "saab": "Saab", "сааб": "Saab",
    "scion": "Scion", "сайон": "Scion",
    "pontiac": "Pontiac", "понтиак": "Pontiac", "понтіак": "Pontiac",
    "saturn": "Saturn", "сатурн": "Saturn",
    "mercury": "Mercury", "меркьюри": "Mercury",
    "hummer": "Hummer", "хаммер": "Hummer",
    "oldsmobile": "Oldsmobile",
    "plymouth": "Plymouth",
}

SYSTEM_PROMPT = """
Ти — AI-консультант Auction Auto. Ти допомагаєш покупцю авто з аукціонів США.

Твоя роль у цьому виклику — ТІЛЬКИ відповісти на конкретне питання клієнта про автомобіль.
Логіку анкети, пропозицію підбору, номер телефону, ліди, тарифи Auction Auto та доставку
контролює Python-код, тому НЕ проси телефон, НЕ пропонуй менеджера і НЕ починай анкету сам.

Правила:
- відповідай мовою поточного повідомлення клієнта;
- звертайся на "Ви";
- коротко і практично, зазвичай 1–4 речення, довше лише якщо клієнт просить перелік;
- завжди враховуй переданий контекст: марка, модель, рік, пробіг, комплектація;
- не підмінюй модельний рік іншим;
- не вигадуй актуальні лоти, ціну авто на торгах, "під ключ", доставку, порт, строки,
  комісії або інші бізнес-умови Auction Auto;
- якщо питають комплектації/двигун/коробку/батарею/потужність/привід/запас ходу/роки,
  використовуй веб-пошук і перевіряй саме потрібний рік/ринок;
- якщо надійно перевірити технічний факт не вдалося — прямо скажи про це;
- не видавай себе за людину: якщо питають, скажи, що ти AI-консультант Auction Auto.
""".strip()

EXTRACTOR_PROMPT = """
Ти витягуєш параметри автомобіля з ОДНОГО повідомлення клієнта.
Поверни ТІЛЬКИ JSON-об'єкт, без пояснень і markdown.

Ключі:
brand, model, year, mileage, trim, budget, engine, drive, battery, color.

Правила:
- використовуй тільки те, що прямо сказано у поточному повідомленні;
- не вигадуй пропущені значення;
- brand/model нормалізуй до звичної назви (наприклад Genesis, G80);
- year зберігай як "2020", "2018-2020", "2015+" тощо;
- mileage зберігай разом з одиницею/обмеженням;
- trim — тільки якщо комплектацію прямо названо;
- якщо значення не вказано — null.
""".strip()
