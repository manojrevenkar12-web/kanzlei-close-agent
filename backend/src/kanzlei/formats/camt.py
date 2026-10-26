"""Bank statements in ISO 20022 camt.053 (versions .02 to .08), as German banks deliver them.

A statement whose entries do not add up from the opening to the closing balance is rejected:
booking from an incomplete statement would silently lose payments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from xml.etree.ElementTree import Element

from kanzlei.domain.money import parse_amount
from kanzlei.domain.text import normalize_iban
from kanzlei.formats.xml import FormatError, every, kid, parse_xml, text


@dataclass(frozen=True)
class Entry:
    seq: int
    booking_date: date
    value_date: date | None
    amount_cents: int  # signed: + money in, - money out
    currency: str
    counterparty_name: str
    counterparty_iban: str | None
    remittance: str
    end_to_end_id: str | None
    mandate_id: str | None
    bank_code: str | None
    reference: str | None


@dataclass(frozen=True)
class Statement:
    statement_id: str
    iban: str
    from_date: date | None
    to_date: date | None
    opening_cents: int
    closing_cents: int
    entries: list[Entry] = field(default_factory=list)


def _date(el: Element | None, path: str) -> date | None:
    t = text(el, path + "/Dt") or text(el, path + "/DtTm") or text(el, path)
    return date.fromisoformat(t[:10]) if t else None


def _balance(stmt: Element, code: str) -> int | None:
    for bal in every(stmt, "Bal"):
        if text(bal, "Tp/CdOrPrtry/Cd") == code:
            amt = text(bal, "Amt")
            if amt is None:
                continue
            cents = parse_amount(amt)
            return cents if text(bal, "CdtDbtInd") == "CRDT" else -cents
    return None


def _currency(ntry: Element) -> str:
    amt = kid(ntry, "Amt")
    return amt.attrib.get("Ccy", "EUR") if amt is not None else "EUR"


def parse_camt053(data: bytes) -> list[Statement]:
    root = parse_xml(data)
    container = kid(root, "BkToCstmrStmt")
    if container is None:
        raise FormatError("not a camt.053 document (no BkToCstmrStmt)")
    out: list[Statement] = []
    for stmt in every(container, "Stmt"):
        iban = normalize_iban(text(stmt, "Acct/Id/IBAN"))
        if not iban:
            raise FormatError("statement without account IBAN")
        opening = _balance(stmt, "OPBD")
        if opening is None:
            opening = _balance(stmt, "PRCD")
        closing = _balance(stmt, "CLBD")
        if opening is None or closing is None:
            raise FormatError("statement without opening or closing balance")
        entries: list[Entry] = []
        for seq, ntry in enumerate(every(stmt, "Ntry"), start=1):
            if (text(ntry, "Sts/Cd") or text(ntry, "Sts") or "BOOK") != "BOOK":
                continue  # pending entries are not bookkeeping facts yet
            amt = text(ntry, "Amt")
            ind = text(ntry, "CdtDbtInd")
            if amt is None or ind not in ("CRDT", "DBIT"):
                raise FormatError(f"entry {seq}: amount or direction missing")
            cents = parse_amount(amt)
            signed = cents if ind == "CRDT" else -cents
            tx = kid(ntry, "NtryDtls/TxDtls")
            party = "Dbtr" if ind == "CRDT" else "Cdtr"
            name = (
                text(tx, f"RltdPties/{party}/Pty/Nm")
                or text(tx, f"RltdPties/{party}/Nm")
                or text(tx, f"RltdPties/Ultmt{party}/Nm")
                or text(ntry, "AddtlNtryInf")
                or ""
            )
            iban_cp = normalize_iban(text(tx, f"RltdPties/{party}Acct/Id/IBAN"))
            remit = " ".join(t for t in (text(u) for u in every(tx, "RmtInf/Ustrd")) if t)
            if not remit:
                remit = text(tx, "AddtlTxInf") or text(ntry, "AddtlNtryInf") or ""
            booking = _date(ntry, "BookgDt")
            if booking is None:
                raise FormatError(f"entry {seq}: booking date missing")
            entries.append(
                Entry(
                    seq=seq,
                    booking_date=booking,
                    value_date=_date(ntry, "ValDt"),
                    amount_cents=signed,
                    currency=_currency(ntry),
                    counterparty_name=name.strip(),
                    counterparty_iban=iban_cp,
                    remittance=remit.strip(),
                    end_to_end_id=(e2e if (e2e := text(tx, "Refs/EndToEndId")) and e2e != "NOTPROVIDED" else None),
                    mandate_id=text(tx, "Refs/MndtId"),
                    bank_code=text(ntry, "BkTxCd/Prtry/Cd") or text(ntry, "BkTxCd/Domn/Fmly/SubFmlyCd"),
                    reference=text(ntry, "AcctSvcrRef") or text(ntry, "NtryRef"),
                )
            )
        total = sum(e.amount_cents for e in entries)
        if opening + total != closing:
            raise FormatError(
                f"statement {text(stmt, 'Id')}: entries sum to {total} cents but balances differ by {closing - opening}"
            )
        out.append(
            Statement(
                statement_id=text(stmt, "Id") or "",
                iban=iban,
                from_date=_date(stmt, "FrToDt/FrDtTm"),
                to_date=_date(stmt, "FrToDt/ToDtTm"),
                opening_cents=opening,
                closing_cents=closing,
                entries=entries,
            )
        )
    if not out:
        raise FormatError("camt.053 without statements")
    return out
