"""One invoice structure for every source: XRechnung (UBL or CII), ZUGFeRD, or a PDF layout read."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass
class Party:
    name: str = ""
    street: str = ""
    postcode: str = ""
    city: str = ""
    country: str = ""
    vat_id: str | None = None
    tax_no: str | None = None

    @property
    def has_address(self) -> bool:
        return bool(self.street and (self.postcode or self.city))


@dataclass
class InvoiceLine:
    description: str
    net_cents: int
    rate: int | None
    category: str | None  # UNTDID 5305: S, AE, K, G, E, Z, O
    quantity: float = 1.0


@dataclass
class TaxBreakdown:
    category: str
    rate: int
    base_cents: int
    tax_cents: int
    exemption: str | None = None


@dataclass
class Invoice:
    source: str  # xrechnung-ubl | xrechnung-cii | zugferd | pdf | llm
    invoice_no: str | None = None
    type_code: str = "380"  # 380 invoice, 381 credit note
    issue_date: date | None = None
    delivery_from: date | None = None
    delivery_to: date | None = None
    currency: str = "EUR"
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    seller_iban: str | None = None
    lines: list[InvoiceLine] = field(default_factory=list)
    taxes: list[TaxBreakdown] = field(default_factory=list)
    net_cents: int | None = None
    tax_cents: int | None = None
    gross_cents: int | None = None
    payable_cents: int | None = None
    due_date: date | None = None
    payment_terms: str = ""
    notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)  # what the reader noticed (totals that do not add up)

    @property
    def is_credit_note(self) -> bool:
        return self.type_code in ("381", "261")

    @property
    def text(self) -> str:
        """What a classifier reads: seller, lines, notes."""
        parts = [self.seller.name, *(ln.description for ln in self.lines), *self.notes]
        return " ".join(p for p in parts if p)

    def check_totals(self) -> None:
        """Records (does not raise) totals that do not add up; the rules decide what that means."""
        if self.taxes and self.net_cents is not None:
            base = sum(t.base_cents for t in self.taxes)
            if base != self.net_cents:
                self.issues.append(f"Steueraufschlüsselung ({base}) ≠ Nettosumme ({self.net_cents})")
        for t in self.taxes:
            if t.category == "S":
                expect = round(t.base_cents * t.rate / 100)
                if abs(expect - t.tax_cents) > 1:
                    self.issues.append(f"Steuer {t.rate} % auf {t.base_cents} ergibt {expect}, nicht {t.tax_cents}")
        if None not in (self.net_cents, self.tax_cents, self.gross_cents):
            assert self.net_cents is not None and self.tax_cents is not None and self.gross_cents is not None
            if self.net_cents + self.tax_cents != self.gross_cents:
                self.issues.append("Netto + Steuer ≠ Brutto")

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("issue_date", "delivery_from", "delivery_to", "due_date"):
            v = getattr(self, k)
            d[k] = v.isoformat() if v else None
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Invoice:
        def dt(v: Any) -> date | None:
            return date.fromisoformat(v) if v else None

        return cls(
            source=d["source"],
            invoice_no=d.get("invoice_no"),
            type_code=d.get("type_code", "380"),
            issue_date=dt(d.get("issue_date")),
            delivery_from=dt(d.get("delivery_from")),
            delivery_to=dt(d.get("delivery_to")),
            currency=d.get("currency", "EUR"),
            seller=Party(**d.get("seller", {})),
            buyer=Party(**d.get("buyer", {})),
            seller_iban=d.get("seller_iban"),
            lines=[InvoiceLine(**x) for x in d.get("lines", [])],
            taxes=[TaxBreakdown(**x) for x in d.get("taxes", [])],
            net_cents=d.get("net_cents"),
            tax_cents=d.get("tax_cents"),
            gross_cents=d.get("gross_cents"),
            payable_cents=d.get("payable_cents"),
            due_date=dt(d.get("due_date")),
            payment_terms=d.get("payment_terms", ""),
            notes=list(d.get("notes", [])),
            issues=list(d.get("issues", [])),
        )
