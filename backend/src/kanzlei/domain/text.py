"""Names, IBANs and tokens: the small text work that matching and memory need."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_LEGAL = re.compile(
    r"\b(gmbh\s*&\s*co\.?\s*kg|gmbh|mbh|ug|haftungsbeschränkt|ag|kg|ohg|gbr|e\.?\s?k\.?|e\.?\s?v\.?|se|ltd|limited|"
    r"inc|llc|b\.?v\.?|s\.?a\.?r?\.?l?\.?|s\.?r\.?l\.?|oy|ab|as|aps|plc|co|und|&|partner|partg|mbb)\b\.?"
)
_NON_WORD = re.compile(r"[^0-9a-zäöüß]+")
_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d /-]{7,}\d)")
_VAT_ID = re.compile(r"\b[A-Z]{2}[0-9A-Z]{8,12}\b")
_TAX_NO = re.compile(r"\b\d{2,3}/\d{3}/\d{4,5}\b")


def fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def normalize_name(name: str) -> str:
    """'Telekom Deutschland GmbH' -> 'telekom deutschland'. Used as a memory key."""
    s = fold(name)
    s = _LEGAL.sub(" ", s)
    s = _NON_WORD.sub(" ", s)
    return " ".join(w for w in s.split() if len(w) > 1 or w.isdigit())


def name_similarity(a: str, b: str) -> float:
    """0..1: the better of token overlap and character similarity of the normalized names."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb)
    contained = 1.0 if (ta <= tb or tb <= ta) else 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    return max(jac, 0.9 * contained, seq)


def normalize_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    s = re.sub(r"\s+", "", iban).upper()
    return s or None


def iban_valid(iban: str | None) -> bool:
    s = normalize_iban(iban)
    if not s or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    moved = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def country_of_vat_id(vat_id: str | None) -> str | None:
    if not vat_id:
        return None
    v = vat_id.strip().upper()
    if v.startswith("EL"):
        return "GR"
    return v[:2] if len(v) > 4 and v[:2].isalpha() else None


def tokens(text: str) -> list[str]:
    return [w for w in _NON_WORD.sub(" ", fold(text)).split() if len(w) > 1]


def redact(text: str, kinds: tuple[str, ...] = ("iban", "email", "phone", "tax_id")) -> str:
    """Removes what a model never needs to read a payment (before any external call)."""
    out = text
    if "iban" in kinds:
        out = _IBAN.sub("[IBAN]", out)
    if "email" in kinds:
        out = _EMAIL.sub("[E-MAIL]", out)
    if "tax_id" in kinds:
        out = _TAX_NO.sub("[STEUERNUMMER]", out)
        out = _VAT_ID.sub("[UST-ID]", out)
    if "phone" in kinds:
        out = _PHONE.sub("[TELEFON]", out)
    return out


def find_invoice_numbers(remittance: str) -> list[str]:
    """Candidate invoice numbers in a payment reference ('RE 2026-0412', 'Rg.Nr. 4711')."""
    s = remittance.upper()
    out = re.findall(r"(?:RE|RG|RECHNUNG|INVOICE|INV|RECHN)[\s.\-:NR]*([A-Z0-9][A-Z0-9\-/]{2,})", s)
    out += re.findall(r"\b([A-Z]{0,4}-?\d{4,}(?:[-/]\d{2,})*)\b", s)
    seen: list[str] = []
    for x in out:
        x = x.strip("-/")
        if x and x not in seen:
            seen.append(x)
    return seen
