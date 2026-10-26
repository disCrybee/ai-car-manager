"""Small deterministic safeguards for the isolated HelpCrunch testing chat."""
import re

def fresh_consultation(text):
    if not isinstance(text, str):
        return False
    t = text.casefold().strip()
    greeting = bool(re.search(r"^(?:добрий\s+(?:день|вечір|ранок)|вітаю|привіт|здравствуйте|добрый\s+день)[!,.\s]*", t))
    intent = any(k in t for k in ("цікавить", "шукаю", "хочу авто", "хочу машину", "потрібне авто", "потрібна машина"))
    return greeting and intent

def low_usd_budget_reply(text):
    if not isinstance(text, str):
        return None
    t = text.casefold().replace(" ", "")
    matches = re.findall(r"(\d{1,2}(?:[.,]\d{3})?|\d{4,5})(?:$|usd|долар(?:ів|и|а)?)", t)
    if not matches:
        return None
    amount = int(matches[-1].replace(".", "").replace(",", ""))
    if not 1000 <= amount < 10000:
        return None
    amount_label = f"{amount:,}".replace(",", " ")
    return (f"У бюджет до ${amount_label} вибір авто зі США з урахуванням доставки та оформлення "
            "буде дуже обмеженим. Зазвичай варто орієнтуватися приблизно від $10 000, "
            "але можемо розглянути доступні варіанти. Який тип авто Вам ближчий: седан чи кросовер?")
