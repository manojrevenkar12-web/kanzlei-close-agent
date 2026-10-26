"""Deterministic identifiers for invented businesses: IBANs with a valid checksum, VAT ids."""

from __future__ import annotations

import hashlib
import random


def seeded(*parts: object) -> random.Random:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def iban(country: str, seed: str) -> str:
    r = seeded("iban", country, seed)
    lengths = {"DE": 18, "AT": 16, "NL": 14, "IE": 18, "FR": 23, "PL": 24, "BE": 12, "LU": 16, "ES": 20, "IT": 23}
    if country == "NL":
        bban = "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4)) + "".join(
            str(r.randrange(10)) for _ in range(10)
        )
    elif country == "IE":
        bban = "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4)) + "".join(
            str(r.randrange(10)) for _ in range(14)
        )
    else:
        bban = "".join(str(r.randrange(10)) for _ in range(lengths.get(country, 18)))
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{bban}"


def vat_id(country: str, seed: str) -> str:
    r = seeded("vat", country, seed)
    n = {"DE": 9, "AT": 8, "NL": 12, "IE": 8, "FR": 11, "PL": 10, "BE": 10, "LU": 8, "ES": 9, "IT": 11}.get(country, 9)
    body = "".join(str(r.randrange(10)) for _ in range(n))
    if country == "AT":
        body = "U" + body
    if country == "NL":
        body = body[:9] + "B" + body[10:]
    if country == "IE":
        body = body[:7] + "W"
    return f"{country}{body}"


def tax_no(seed: str) -> str:
    r = seeded("stnr", seed)
    return f"{r.randrange(200, 240)}/{r.randrange(100, 999)}/{r.randrange(10000, 99999)}"
