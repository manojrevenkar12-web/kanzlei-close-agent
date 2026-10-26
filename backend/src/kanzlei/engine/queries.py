"""Questions to the client, in plain German, one bundle per client and month.

A question has fixed answer options. An answer is applied by rules (domain/tax.py), so what the
client says is turned into bookings the same way every time, and staff see it before the month
is signed off.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from kanzlei.domain.models import CLIENT_FLAGS
from kanzlei.domain.money import fmt_de

OPTIONS: dict[str, list[dict[str, Any]]] = {
    "missing_receipt": [
        {"value": "upload", "label": "Beleg hochladen", "needs": ["file"]},
        {"value": "no_receipt", "label": "Es gibt keinen Beleg", "needs": ["purpose"]},
        {"value": "private", "label": "Das war privat"},
    ],
    "private_or_business": [
        {"value": "private", "label": "Privat"},
        {"value": "business", "label": "Betrieblich", "needs": ["purpose"]},
    ],
    "meals_details": [
        {"value": "details", "label": "Anlass und Teilnehmer angeben", "needs": ["occasion", "participants"]},
        {"value": "private", "label": "Das war privat"},
    ],
    "unknown_credit": [
        {"value": "customer", "label": "Zahlung eines Kunden", "needs": ["invoice_no"]},
        {"value": "private_deposit", "label": "Privateinlage"},
        {"value": "refund", "label": "Erstattung eines Lieferanten"},
        {"value": "other", "label": "Etwas anderes", "needs": ["note"]},
    ],
    "invoice_incomplete": [
        {"value": "upload", "label": "Korrigierte Rechnung hochladen", "needs": ["file"]},
        {"value": "not_available", "label": "Es gibt keine korrigierte Rechnung"},
    ],
}


def _de_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def question_for(reason: str, *, on: date, amount_cents: int, counterparty: str, details: str = "") -> str:
    who = counterparty or "unbekannt"
    what = f"{'Zahlungseingang' if amount_cents > 0 else 'Zahlung'} vom {_de_date(on)} über {fmt_de(abs(amount_cents))} ({who})"
    match reason:
        case "missing_receipt":
            return f"{what}: Uns fehlt der Beleg. Bitte laden Sie die Rechnung hoch."
        case "private_or_business":
            return f"{what}: War das privat oder betrieblich?"
        case "meals_details":
            return f"{what}: Für die Bewirtung brauchen wir den Anlass und die Teilnehmer."
        case "unknown_credit":
            return f"{what}: Wofür war dieser Eingang?"
        case "invoice_incomplete":
            extra = f" Es fehlen: {details}." if details else ""
            return f"{what}: Die Rechnung ist für den Vorsteuerabzug unvollständig.{extra} Bitte fordern Sie beim Lieferanten eine korrigierte Rechnung an."
    return f"{what}: {CLIENT_FLAGS.get(reason, 'Rückfrage')}"


def bundle_message(
    *, client_name: str, contact_name: str, firm_name: str, period: str, questions: list[str], link: str, due: date
) -> tuple[str, str]:
    month = date(int(period[:4]), int(period[5:7]), 1).strftime("%m/%Y")
    subject = f"Buchhaltung {month}: {len(questions)} offene {'Frage' if len(questions) == 1 else 'Fragen'}"
    greeting = f"Guten Tag {contact_name}," if contact_name else "Guten Tag,"
    items = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))
    body = (
        f"{greeting}\n\n"
        f"für die Buchhaltung {month} von {client_name} brauchen wir noch Ihre Hilfe:\n\n"
        f"{items}\n\n"
        f"Sie können alles hier beantworten und Belege hochladen: {link}\n"
        f"Bitte bis zum {_de_date(due)}.\n\n"
        f"Vielen Dank\n{firm_name}"
    )
    return subject, body


def answers_for(reason: str, answer: dict[str, Any]) -> dict[str, Any]:
    """A portal answer -> the `answers` the proposal builder understands."""
    choice = answer.get("choice")
    out: dict[str, Any] = {"answered": reason, "choice": choice}
    if choice == "private":
        out["family"] = "private_withdrawal"
    elif choice == "private_deposit":
        out["family"] = "private_deposit"
    elif choice == "no_receipt":
        out["receipt"] = "no_receipt"
        out["purpose"] = str(answer.get("purpose", ""))[:200]
    elif choice == "not_available":
        out["receipt"] = "not_available"
    elif choice == "details":
        out["meals_details"] = True
        out["occasion"] = str(answer.get("occasion", ""))[:200]
        out["participants"] = str(answer.get("participants", ""))[:300]
    elif choice == "customer":
        out["invoice_no"] = str(answer.get("invoice_no", ""))[:40]
    elif choice in ("business", "refund", "other"):
        out["needs_review"] = True
        out["note"] = str(answer.get("purpose") or answer.get("note") or "")[:300]
    return out


def valid_answer(reason: str, answer: dict[str, Any]) -> bool:
    opts = {o["value"]: o for o in OPTIONS.get(reason, [])}
    choice = answer.get("choice")
    if choice not in opts:
        return False
    for need in opts[choice].get("needs", []):
        if need == "file":
            if not answer.get("document_id"):
                return False
        elif not str(answer.get(need, "")).strip():
            return False
    return True
