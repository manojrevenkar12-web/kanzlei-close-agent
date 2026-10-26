"""The optional model reader (Claude via the Messages API).

Called only when the firm has a § 62a StBerG agreement on record, the key is configured, and
the use is enabled in config/llm.yaml. Text is redacted first. What comes back is checked before
use: a family must be one of ours; an invoice must add up and match the payment. The model never
decides a tax code or an account.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from kanzlei.config import LlmConfig, families
from kanzlei.domain.money import parse_amount
from kanzlei.domain.text import redact
from kanzlei.formats.invoice import Invoice, InvoiceLine, Party, TaxBreakdown

Transport = Callable[[dict[str, Any]], dict[str, Any]]


def _http_transport(cfg: LlmConfig) -> Transport:
    base = os.environ.get(cfg.base_url_env, "https://api.anthropic.com")
    key = os.environ.get(cfg.enabled_if_env, "")

    def send(body: dict[str, Any]) -> dict[str, Any]:
        r = httpx.post(
            f"{base.rstrip('/')}/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body,
            timeout=cfg.timeout_seconds,
        )
        r.raise_for_status()
        out: dict[str, Any] = r.json()
        return out

    return send


class ModelReader:
    def __init__(self, cfg: LlmConfig, transport: Transport | None = None) -> None:
        self.cfg = cfg
        self.transport = transport or _http_transport(cfg)
        self.calls = 0

    def _ask(self, system: str, user: str) -> str:
        self.calls += 1
        body = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": redact(user, self.cfg.redact)}],
        }
        resp = self.transport(body)
        return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")

    def suggest_family(self, text: str) -> str | None:
        if not self.cfg.uses.get("suggest_family"):
            return None
        fams = families()
        listing = "\n".join(f"{k}: {v.label}" for k, v in fams.items())
        system = (
            "Du hilfst einer Steuerkanzlei, Zahlungen einer Buchungsfamilie zuzuordnen. "
            "Antworte nur mit dem Schlüssel einer Familie aus der Liste oder mit 'unklar'."
        )
        try:
            out = self._ask(system, f"Familien:\n{listing}\n\nZahlung:\n{text}").strip().split()[0].strip(".'\"`")
        except Exception:
            return None
        return out if out in fams else None

    def read_invoice(self, text: str, expected_gross: int | None = None) -> Invoice | None:
        if not self.cfg.uses.get("read_invoice"):
            return None
        system = (
            "Lies die Rechnung und antworte nur mit JSON: "
            '{"seller": str, "invoice_no": str|null, "issue_date": "YYYY-MM-DD"|null, '
            '"gross": "1234,56", "taxes": [{"rate": 19, "base": "100,00", "tax": "19,00"}], "lines": [str]}'
        )
        try:
            raw = self._ask(system, text[:6000])
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                return None
            d = json.loads(m.group(0))
            inv = Invoice(source="llm")
            inv.seller = Party(name=str(d.get("seller") or ""))
            inv.invoice_no = d.get("invoice_no")
            inv.issue_date = date.fromisoformat(d["issue_date"]) if d.get("issue_date") else None
            inv.gross_cents = parse_amount(str(d["gross"]))
            for t in d.get("taxes", []):
                inv.taxes.append(
                    TaxBreakdown("S", int(t["rate"]), parse_amount(str(t["base"])), parse_amount(str(t["tax"])))
                )
            inv.lines = [InvoiceLine(str(x), 0, None, None) for x in d.get("lines", [])][:20]
        except Exception:
            return None
        # Verify: the parts must add up, and to what was paid if we know it.
        if inv.taxes and sum(t.base_cents + t.tax_cents for t in inv.taxes) != inv.gross_cents:
            return None
        if expected_gross is not None and inv.gross_cents != expected_gross:
            return None
        inv.net_cents = sum(t.base_cents for t in inv.taxes) if inv.taxes else None
        inv.tax_cents = sum(t.tax_cents for t in inv.taxes) if inv.taxes else None
        inv.issues.append("vom Sprachmodell gelesen und geprüft (Summen, Zahlbetrag)")
        return inv
