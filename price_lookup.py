import json
from pathlib import Path
from difflib import get_close_matches


# ==========================================
# ШЛЯХ ДО БАЗИ ПРАЙСІВ
# ==========================================

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "auction_prices.json"


# ==========================================
# ЗАВАНТАЖЕННЯ JSON
# ==========================================

if not DATA_FILE.exists():
    raise FileNotFoundError(
        f"Не знайдено файл прайсів:\n{DATA_FILE}"
    )

with open(DATA_FILE, "r", encoding="utf-8") as file:
    PRICE_DATA = json.load(file)


# ==========================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ==========================================

def normalize(text: str) -> str:
    """
    Приводить назви до однакового вигляду
    для пошуку.
    """

    return (
        str(text)
        .upper()
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )


def normalize_auction(auction: str):
    """
    Розуміє різні варіанти написання аукціону.
    """

    auction = normalize(auction)

    if "COPART" in auction:
        return "Copart"

    if "IAAI" in auction or "IAA" in auction:
        return "IAAI"

    return None


def format_price(price):
    """
    Робить значення тарифу зручним для використання ботом.
    """

    if price is None:
        return {
            "status": "not_found",
            "text": "ціна не вказана",
        }

    if isinstance(price, (int, float)):
        return {
            "status": "ok",
            "value": price,
            "text": f"${price}",
        }

    if isinstance(price, dict):

        status = price.get("status")

        if status == "manual_check":
            return {
                "status": "manual_check",
                "text": "вартість потрібно уточнити",
            }

        if status == "uncertain":
            value = price.get("value")

            return {
                "status": "uncertain",
                "value": value,
                "text": "вартість потрібно уточнити",
            }

        if status == "raw_text":
            return {
                "status": "manual_check",
                "text": "вартість потрібно уточнити",
            }

        if "min" in price and "max" in price:
            return {
                "status": "range",
                "min": price["min"],
                "max": price["max"],
                "text": f"${price['min']}–${price['max']}",
            }

    return {
        "status": "manual_check",
        "text": "вартість потрібно уточнити",
    }


# ==========================================
# ПОШУК ЛОКАЦІЇ COPART / IAAI
# ==========================================

def find_usa_locations(
    auction: str,
    query: str,
    limit: int = 5
):
    """
    Приклад:

    find_usa_locations(
        "Copart",
        "Atlanta North"
    )
    """

    auction_key = normalize_auction(auction)

    if not auction_key:
        return []

    section = PRICE_DATA["usa"].get(auction_key)

    if not section:
        return []

    locations = section.get("locations", [])

    query_normalized = normalize(query)

    # --------------------------------------
    # 1. Точне / часткове співпадіння
    # --------------------------------------

    direct_matches = []

    for item in locations:

        location_name = normalize(
            item.get("location", "")
        )

        if (
            query_normalized in location_name
            or location_name in query_normalized
        ):
            direct_matches.append(item)

    if direct_matches:
        return direct_matches[:limit]

    # --------------------------------------
    # 2. Fuzzy search
    # якщо назва написана неточно
    # --------------------------------------

    normalized_names = {}

    for item in locations:

        original_name = item.get(
            "location",
            ""
        )

        if original_name:
            normalized_names[
                normalize(original_name)
            ] = original_name

    matches = get_close_matches(
        query_normalized,
        list(normalized_names.keys()),
        n=limit,
        cutoff=0.50,
    )

    result = []

    for match in matches:

        original_name = normalized_names[match]

        for item in locations:

            if item.get("location") == original_name:
                result.append(item)
                break

    return result


# ==========================================
# ОТРИМАТИ НАЙКРАЩИЙ МАРШРУТ
# ==========================================

def get_best_usa_route(
    auction: str,
    location: str
):
    """
    Повертає знайдену локацію
    та всі доступні маршрути/порти.
    """

    matches = find_usa_locations(
        auction,
        location,
        limit=1,
    )

    if not matches:
        return None

    item = matches[0]

    routes = []

    for route in item.get("routes", []):

        routes.append({
            "port": route.get("port"),
            "price": format_price(
                route.get("price")
            ),
        })

    return {
        "auction": item.get("auction"),
        "location": item.get("location"),
        "routes": routes,
        "moto_atv": format_price(
            item.get("moto_atv")
        ),
    }


# ==========================================
# ТАРИФИ ПО ТИПУ АВТО
# ==========================================

def get_vehicle_rates(
    auction: str,
    category: str
):
    """
    Повертає портові/морські тарифи
    для конкретної категорії авто.
    """

    auction_key = normalize_auction(auction)

    if not auction_key:
        return None

    section = PRICE_DATA["usa"].get(
        auction_key
    )

    if not section:
        return None

    rates = section.get(
        "vehicle_rates",
        {}
    )

    # точне співпадіння
    if category in rates:
        return rates[category]

    category_normalized = normalize(category)

    # неточне співпадіння
    for key, value in rates.items():

        if category_normalized in normalize(key):
            return value

    return None


# ==========================================
# КАНАДА
# ==========================================

def find_canada_city(
    city: str,
    limit: int = 5
):
    """
    Пошук тарифів по Канаді.
    """

    rows = PRICE_DATA[
        "canada"
    ].get(
        "locations",
        []
    )

    query_normalized = normalize(city)

    direct_matches = []

    for row in rows:

        city_name = normalize(
            row.get("city", "")
        )

        if (
            query_normalized in city_name
            or city_name in query_normalized
        ):
            direct_matches.append(row)

    if direct_matches:
        return direct_matches[:limit]

    normalized_names = {}

    for row in rows:

        original_name = row.get(
            "city",
            ""
        )

        if original_name:
            normalized_names[
                normalize(original_name)
            ] = original_name

    matches = get_close_matches(
        query_normalized,
        list(normalized_names.keys()),
        n=limit,
        cutoff=0.50,
    )

    result = []

    for match in matches:

        original_name = normalized_names[match]

        for row in rows:

            if row.get("city") == original_name:
                result.append(row)
                break

    return result


# ==========================================
# ТЕСТ
# ==========================================

if __name__ == "__main__":

    print("\n=== ТЕСТ ПОШУКУ ПРАЙСУ ===\n")

    result = get_best_usa_route(
        "Copart",
        "Atlanta North"
    )

    if not result:

        print(
            "Локацію не знайдено."
        )

    else:

        print(
            "Аукціон:",
            result["auction"]
        )

        print(
            "Локація:",
            result["location"]
        )

        print("\nМаршрути:")

        for route in result["routes"]:

            print(
                f"- {route['port']}: "
                f"{route['price']['text']}"
            )