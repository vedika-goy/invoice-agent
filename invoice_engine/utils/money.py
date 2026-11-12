"""Exact money and quantity arithmetic, parsing of printed numbers, and display formatting."""
import re
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
UNIT_PRICE_PRECISION = Decimal("0.0001")
UNCOUNTABLE_UNITS = {"each", "dozen", "gal", "lb", "kg"}
IRREGULAR_UNIT_PLURALS = {"loaf": "loaves"}

# matches the digits of a printed number such as "$2,520.00", "(38.50)" or "1,000"
_PRINTED_NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def to_money(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def to_quantity(value: float | int | str | Decimal) -> Decimal:
    quantity = Decimal(str(value))
    if quantity == quantity.to_integral_value():
        return quantity.quantize(Decimal(1))
    return quantity.normalize()


def parse_printed_number(printed_text: str) -> Decimal | None:
    """Unsigned number inside printed text; the sign is ignored because amounts are read as positives."""
    match = _PRINTED_NUMBER_PATTERN.search(printed_text)
    if match is None:
        return None
    return Decimal(match.group().replace(",", ""))


def format_money(amount: Decimal, currency_code: str | None = "USD") -> str:
    sign = "-" if amount < 0 else ""
    digits = f"{abs(amount):,.2f}"
    if currency_code in (None, "USD"):
        return f"{sign}${digits}"
    return f"{sign}{digits} {currency_code}"


def format_quantity(quantity: Decimal) -> str:
    if quantity == quantity.to_integral_value():
        return f"{int(quantity):,}"
    return f"{quantity.normalize():,}"


def format_quantity_with_unit(quantity: Decimal, unit: str) -> str:
    """'1,000 bags', '1 bag', '15 dozen'."""
    if quantity == 1 or unit in UNCOUNTABLE_UNITS:
        return f"{format_quantity(quantity)} {unit}"
    plural = IRREGULAR_UNIT_PLURALS.get(unit, unit + ("es" if unit.endswith(("s", "x", "ch", "sh")) else "s"))
    return f"{format_quantity(quantity)} {plural}"


def format_percent(percent: Decimal, has_sign: bool = False) -> str:
    # Differences under 0.1% keep two decimals, so "0.01%" doesn't round to a misleading "0%".
    precision = Decimal("0.01") if Decimal(0) < abs(percent) < Decimal("0.1") else Decimal("0.1")
    rounded = percent.quantize(precision, rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        rounded = rounded.quantize(Decimal(1))
    return f"{rounded:+}%" if has_sign else f"{rounded}%"


def build_percent_difference(actual: Decimal, reference: Decimal) -> Decimal:
    """(actual - reference) / reference as a percentage; reference must not be zero."""
    return (actual - reference) / reference * Decimal(100)
