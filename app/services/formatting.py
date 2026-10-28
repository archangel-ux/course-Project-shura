import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Almaty"))


def tiyn_to_decimal(tiyn):
    return Decimal(int(tiyn or 0)) / Decimal(100)


def format_number(value):
    return f"{int(value or 0):,}".replace(",", " ")


def format_signed(value):
    value = int(value or 0)
    return ("+" if value > 0 else "−" if value < 0 else "") + format_number(abs(value))


def format_money(tiyn):
    text = f"{tiyn_to_decimal(tiyn):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₸"


def format_money_short(tiyn):
    """Whole tenge for big headline numbers."""
    amount = int(tiyn_to_decimal(tiyn))
    return f"{format_number(amount)} ₸"


def money_to_input(tiyn):
    """150050 → '1500,50', 150000 → '1500'."""
    text = f"{tiyn_to_decimal(tiyn):.2f}".replace(".", ",")
    return text[:-3] if text.endswith(",00") else text


def money_for_csv(tiyn):
    return f"{tiyn_to_decimal(tiyn):.2f}".replace(".", ",")


def parse_timestamp(value):
    """Postgres timestamptz string → aware datetime in the local timezone."""
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).replace("Z", "+00:00")
        # Python < 3.11 cannot parse 1–5 digit fractions; PostgREST may send them
        if "." in text:
            head, tail = text.split(".", 1)
            digits = "".join(ch for ch in tail if ch.isdigit())
            zone = tail[len(digits):]
            text = f"{head}.{digits[:6].ljust(6, '0')}{zone}"
        moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(LOCAL_TZ)


def format_datetime(value):
    moment = parse_timestamp(value)
    return moment.strftime("%d.%m.%Y %H:%M") if moment else ""


def format_date(value):
    moment = parse_timestamp(value)
    return moment.strftime("%d.%m.%Y") if moment else ""
