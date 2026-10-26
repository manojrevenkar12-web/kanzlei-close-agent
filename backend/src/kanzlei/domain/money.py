"""Money in integer cents. German formats in and out; rounding half up, as on an invoice."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_GERMAN = re.compile(r"^[+-]?\d{1,3}(\.\d{3})*(,\d{1,2})?$|^[+-]?\d+(,\d{1,2})?$")


def parse_amount(text: str) -> int:
    """'1.234,56' (German), '1234.56' (XML) or '1234,5' -> cents. Raises ValueError otherwise."""
    s = text.strip().replace("€", "").replace("EUR", "").replace(" ", "").replace(" ", "")
    if not s:
        raise ValueError("empty amount")
    if _GERMAN.match(s):
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"not an amount: {text!r}") from e
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_decimal_str(cents: int) -> str:
    """Cents -> '1234.56' (XML)."""
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{c // 100}.{c % 100:02d}"


def fmt_de(cents: int, *, currency: bool = True) -> str:
    """Cents -> '1.234,56 €'."""
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    euros = f"{c // 100:,}".replace(",", ".")
    out = f"{sign}{euros},{c % 100:02d}"
    return f"{out} €" if currency else out


def fmt_datev(cents: int) -> str:
    """DATEV amount field: decimal comma, no thousands separator, always positive."""
    c = abs(cents)
    return f"{c // 100},{c % 100:02d}"


def round_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounded half away from zero."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    q, r = divmod(abs(numerator), denominator)
    if 2 * r >= denominator:
        q += 1
    return q if numerator >= 0 else -q


def split_gross(gross_cents: int, rate: int) -> tuple[int, int]:
    """Gross -> (net, tax) at `rate` percent; the tax is rounded, the net is the remainder."""
    tax = round_half_up(gross_cents * rate, 100 + rate)
    return gross_cents - tax, tax


def tax_on_net(net_cents: int, rate: int) -> int:
    return round_half_up(net_cents * rate, 100)


def share(cents: int, fraction: float) -> int:
    """A share of an amount, rounded half up (e.g. the deductible 70 % of a meal)."""
    return round_half_up(round(cents * fraction * 10000), 10000)
