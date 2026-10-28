"""Input parsing and validation.

Errors carry an i18n key (and field-name keys as params) so the page can show
them in the user's language. Money becomes integer tiyn via Decimal — no floats.
"""

import re
from decimal import Decimal, InvalidOperation

MAX_QUANTITY = 1_000_000_000
MAX_MONEY = Decimal("1000000000")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(Exception):
    def __init__(self, key, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def require_text(value, field, max_length=150):
    text = str(value or "").strip()
    if not text:
        raise ValidationError("err.required", field=field)
    if len(text) > max_length:
        raise ValidationError("err.too_long", field=field, max=max_length)
    return text


def optional_text(value, field, max_length=150):
    text = str(value or "").strip()
    if len(text) > max_length:
        raise ValidationError("err.too_long", field=field, max=max_length)
    return text


def parse_quantity(value, field, allow_zero=True):
    text = str(value or "").replace(" ", "").replace(" ", "")
    if not text:
        if allow_zero:
            return 0
        raise ValidationError("err.required", field=field)
    try:
        number = int(text)
    except ValueError:
        raise ValidationError("err.integer", field=field) from None
    if number < 0:
        raise ValidationError("err.negative", field=field)
    if number == 0 and not allow_zero:
        raise ValidationError("err.positive", field=field)
    if number > MAX_QUANTITY:
        raise ValidationError("err.too_large", field=field)
    return number


def parse_money(value, field):
    """'1 500,50' or '1500.5' → 150050 tiyn."""
    text = (
        str(value or "")
        .replace(" ", "")
        .replace(" ", "")
        .replace("₸", "")
        .replace(",", ".")
    )
    if not text:
        return 0
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValidationError("err.money", field=field) from None
    if not amount.is_finite():
        raise ValidationError("err.money", field=field)
    if amount < 0:
        raise ValidationError("err.negative", field=field)
    if amount > MAX_MONEY:
        raise ValidationError("err.too_large", field=field)
    if amount != amount.quantize(Decimal("0.01")):
        raise ValidationError("err.money_decimals", field=field)
    return int(amount * 100)


def parse_email(value, field="field.email", required=True):
    text = str(value or "").strip().lower()
    if not text and not required:
        return ""
    if not EMAIL_PATTERN.match(text) or len(text) > 120:
        raise ValidationError("err.email_invalid", field=field)
    return text


def parse_password(value, confirm=None):
    password = str(value or "")
    if len(password) < 8:
        raise ValidationError("err.password_short")
    if len(password) > 72:
        raise ValidationError("err.too_long", field="field.password", max=72)
    if confirm is not None and password != confirm:
        raise ValidationError("err.password_mismatch")
    return password
