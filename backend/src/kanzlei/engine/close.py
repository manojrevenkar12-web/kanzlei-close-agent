"""The monthly close for one client, on the database.

    import statements and documents  ->  run  ->  staff decide / client answers  ->  VAT return
    ->  sign-off (tax advisor; locks the month)  ->  DATEV export

Every step runs inside the caller's transaction, under the caller's rights (row-level security),
and writes to the protocol (events).
"""

from __future__ import annotations

import calendar
import secrets
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from kanzlei.config import close_config, families, settings, tax_config
from kanzlei.db import Conn, Principal, event
from kanzlei.domain import ustva as ustva_mod
from kanzlei.domain.chart import Account, Chart, chart
from kanzlei.domain.compliance import LABELS, missing_fields
from kanzlei.domain.models import CLIENT_FLAGS, REVIEW_FLAGS, ClientProfile, Line, Proposal, Reason
from kanzlei.domain.text import normalize_iban, normalize_name
from kanzlei.engine import queries as q
from kanzlei.engine.classifier import Classifier
from kanzlei.engine.decision import DecisionModel
from kanzlei.engine.matching import Doc, Match, Tx, match
from kanzlei.engine.memory import ClientMemory, Use
from kanzlei.engine.plausibility import check as plausibility_check
from kanzlei.engine.propose import (
    Context,
    Counterparty,
    OpenItem,
    match_open_item,
    propose_invoice,
    propose_open_item,
    propose_payment,
)
from kanzlei.formats.camt import parse_camt053
from kanzlei.formats.einvoice import parse_einvoice_xml, parse_zugferd
from kanzlei.formats.extf import ExtfBooking, MasterRecord, write_buchungsstapel, write_stammdaten
from kanzlei.formats.invoice import Invoice
from kanzlei.formats.pdfinvoice import pdf_text, read_invoice_pdf
from kanzlei.formats.xml import FormatError
from kanzlei.storage import Store, key_for, sha256


def need(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise CloseError("Datensatz nicht gefunden")
    return row


class CloseError(Exception):
    """A step that cannot be taken in the current state (shown to staff as is)."""


def period_bounds(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def prev_periods(period: str, n: int) -> list[str]:
    y, m = int(period[:4]), int(period[5:7])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return list(reversed(out))


@dataclass
class Engine:
    store: Store
    classifier: Classifier | None
    decision: DecisionModel
    reader_for: Callable[[ClientProfile], Any] | None = None  # returns a ModelReader or None

    # --- loading ---------------------------------------------------------------------------

    def profile(self, conn: Conn, client_id: str) -> ClientProfile:
        r = conn.execute(
            "SELECT c.*, f.chart, f.berater_nr, f.llm_agreement_on FROM clients c JOIN firms f ON f.id = c.firm_id WHERE c.id = %s",
            (client_id,),
        ).fetchone()
        if r is None:
            raise CloseError("Mandant nicht gefunden")
        return ClientProfile(
            id=r["id"],
            firm_id=r["firm_id"],
            name=r["name"],
            chart=r["chart"],
            booking_method=r["booking_method"],
            vat_regime=r["vat_regime"],
            vat_period=r["vat_period"],
            dauerfrist=r["dauerfrist"],
            own_ibans=tuple(normalize_iban(i) or "" for i in r["own_ibans"]),
            vat_id=r["vat_id"],
            mandant_nr=r["mandant_nr"],
            berater_nr=r["berater_nr"],
            fiscal_year_start_month=r["fiscal_year_start_month"],
            llm_allowed=r["llm_agreement_on"] is not None,
        )

    def chart_for(self, conn: Conn, firm_id: str, name: str) -> Chart:
        rows = conn.execute(
            "SELECT account, name, family, role, tax FROM firm_accounts WHERE firm_id = %s AND family IS NOT NULL",
            (firm_id,),
        ).fetchall()
        base = chart(name)
        return (
            base.extend([Account(r["account"], r["name"], r["family"], r["tax"], False, r["role"]) for r in rows])
            if rows
            else base
        )

    def counterparties(self, conn: Conn, client_id: str) -> list[Counterparty]:
        rows = conn.execute(
            "SELECT * FROM counterparties WHERE client_id = %s ORDER BY account", (client_id,)
        ).fetchall()
        return [Counterparty(r["kind"], r["account"], r["name"], r["iban"], r["vat_id"], r["country"]) for r in rows]

    def memory(
        self, conn: Conn, client: ClientProfile, ch: Chart, before: date, cps: list[Counterparty]
    ) -> ClientMemory:
        mem = ClientMemory(close_config())
        by_acct = {c.account: c for c in cps}
        rows = conn.execute(
            """SELECT b.item_id, b.booking_date, b.amount_cents, b.debit, b.credit, b.tax, b.text, b.doc_ref, b.family, b.origin,
                      i.proposal -> 'counterparty' AS cp
               FROM bookings b LEFT JOIN items i ON i.id = b.item_id
               WHERE b.client_id = %s AND b.booking_date < %s""",
            (client.id, before),
        ).fetchall()
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            if r["item_id"] is not None:
                groups[("i", r["item_id"])].append(r)
            else:
                personal = (
                    r["debit"] if ch.is_personal(r["debit"]) else (r["credit"] if ch.is_personal(r["credit"]) else None)
                )
                groups[("h", r["booking_date"], r["doc_ref"], r["text"], personal)].append(r)
        fams = families()
        for key, lines in groups.items():
            fam_lines = [x for x in lines if x["family"] in fams]
            if not fam_lines:
                continue
            main = max(fam_lines, key=lambda x: x["amount_cents"])
            total = sum(x["amount_cents"] for x in lines if x["family"] in fams)
            personal_side = any(ch.is_personal(x["debit"]) or ch.is_personal(x["credit"]) for x in lines)
            bank = ch.system["bank"]
            money_in = any(x["debit"] == bank for x in lines) or any(ch.is_debtor(x["debit"]) for x in lines)
            use = Use(main["family"], main["tax"], total, main["booking_date"], personal_side, money_in)
            if key[0] == "i":
                cp = main["cp"] or {}
                mem.add(iban=cp.get("iban"), name=cp.get("name") or main["text"], use=use)
            else:
                personal = key[4]
                if personal is not None and personal in by_acct:
                    c = by_acct[personal]
                    mem.add(iban=c.iban, name=c.name, use=use)
                else:
                    mem.add(iban=None, name=main["text"], use=use)
        return mem

    def context(self, conn: Conn, client_id: str, period: str) -> Context:
        client = self.profile(conn, client_id)
        ch = self.chart_for(conn, client.firm_id, client.chart)
        start, end = period_bounds(period)
        cps = self.counterparties(conn, client_id)
        reader = self.reader_for(client) if (self.reader_for and client.llm_allowed) else None
        return Context(
            client=client,
            chart=ch,
            memory=self.memory(conn, client, ch, start, cps),
            classifier=self.classifier,
            decision=self.decision,
            tax=tax_config(),
            close=close_config(),
            period_start=start,
            period_end=end,
            counterparties=cps,
            suggest_family=reader.suggest_family if reader else None,
        )

    # --- ingest ----------------------------------------------------------------------------

    def import_statement(
        self, conn: Conn, client_id: str, data: bytes, filename: str, actor: Principal
    ) -> dict[str, Any]:
        client = self.profile(conn, client_id)
        digest = sha256(data)
        if conn.execute(
            "SELECT 1 FROM statements WHERE client_id = %s AND sha256 = %s", (client_id, digest)
        ).fetchone():
            return {"duplicate": True, "statements": 0, "transactions": 0}
        try:
            statements = parse_camt053(data)
        except FormatError as e:
            raise CloseError(f"Kontoauszug abgelehnt: {e}") from e
        added = 0
        for st in statements:
            if client.own_ibans and st.iban not in client.own_ibans:
                raise CloseError(f"Kontoauszug für {st.iban} gehört nicht zu {client.name}")
            sid = need(
                conn.execute(
                    """INSERT INTO statements (client_id, iban, statement_id, sha256, from_date, to_date, opening_cents, closing_cents)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (
                        client_id,
                        st.iban,
                        st.statement_id,
                        digest if len(statements) == 1 else f"{digest}:{st.statement_id}",
                        st.from_date,
                        st.to_date,
                        st.opening_cents,
                        st.closing_cents,
                    ),
                ).fetchone()
            )["id"]
            for entry in st.entries:
                conn.execute(
                    """INSERT INTO transactions (client_id, statement_id, seq, booking_date, value_date, amount_cents, counterparty_name,
                       counterparty_iban, remittance, end_to_end_id, mandate_id, bank_code, period)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        client_id,
                        sid,
                        entry.seq,
                        entry.booking_date,
                        entry.value_date,
                        entry.amount_cents,
                        entry.counterparty_name,
                        entry.counterparty_iban,
                        entry.remittance,
                        entry.end_to_end_id,
                        entry.mandate_id,
                        entry.bank_code,
                        period_of(entry.booking_date),
                    ),
                )
                added += 1
        event(
            conn,
            actor.login,
            "statement.import",
            {"file": filename, "sha256": digest, "transactions": added},
            firm=client.firm_id,
            client=client_id,
        )
        return {"duplicate": False, "statements": len(statements), "transactions": added}

    def read_document(self, data: bytes, filename: str) -> tuple[Invoice, str, str]:
        """-> (invoice, format, media type). Never raises for a readable file; problems go into issues."""
        name = filename.lower()
        if name.endswith(".xml") or data.lstrip()[:5] == b"<?xml":
            inv = parse_einvoice_xml(data)
            return inv, inv.source, "application/xml"
        if data[:4] == b"%PDF":
            z = parse_zugferd(data)
            if z is not None:
                return z, "zugferd", "application/pdf"
            return read_invoice_pdf(data), "pdf", "application/pdf"
        raise CloseError("Nur E-Rechnungen (XML), ZUGFeRD- und PDF-Rechnungen werden angenommen")

    def import_document(
        self,
        conn: Conn,
        client_id: str,
        data: bytes,
        filename: str,
        *,
        source: str,
        direction: str,
        actor: Principal,
        reader: Any = None,
    ) -> dict[str, Any]:
        client = self.profile(conn, client_id)
        digest = sha256(data)
        dup = conn.execute(
            "SELECT id FROM documents WHERE client_id = %s AND sha256 = %s", (client_id, digest)
        ).fetchone()
        if dup:
            return {"id": dup["id"], "duplicate": True}
        try:
            inv, fmt, media = self.read_document(data, filename)
        except FormatError as e:
            raise CloseError(f"Beleg abgelehnt: {e}") from e
        if fmt == "pdf" and inv.gross_cents is None and reader is not None:
            better = reader.read_invoice(pdf_text(data))
            if better is not None:
                inv, fmt = better, "llm"
        same = None
        if inv.invoice_no:
            same = conn.execute(
                "SELECT id FROM documents WHERE client_id = %s AND invoice_no = %s AND lower(seller_name) = lower(%s) AND direction = %s",
                (client_id, inv.invoice_no, inv.seller.name, direction),
            ).fetchone()
        if same:
            inv.issues.append(f"gleiche Rechnungsnummer wie Beleg {same['id']}")
        key = key_for(client_id, digest, filename)
        self.store.put(key, data, media)
        on = inv.issue_date or date.today()
        doc_id = need(
            conn.execute(
                """INSERT INTO documents (client_id, sha256, filename, media_type, storage_key, source, format, direction, invoice, invoice_no,
               issue_date, seller_name, gross_cents, period) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    client_id,
                    digest,
                    filename,
                    media,
                    key,
                    source,
                    fmt,
                    direction,
                    Jsonb(inv.to_json()),
                    inv.invoice_no,
                    inv.issue_date,
                    inv.seller.name,
                    inv.payable_cents or inv.gross_cents,
                    period_of(on),
                ),
            ).fetchone()
        )["id"]
        event(
            conn,
            actor.login,
            "document.import",
            {"id": doc_id, "file": filename, "format": fmt, "sha256": digest},
            firm=client.firm_id,
            client=client_id,
        )
        return {
            "id": doc_id,
            "duplicate": False,
            "format": fmt,
            "issues": inv.issues,
            "same_invoice_no": same["id"] if same else None,
        }

    # --- run -------------------------------------------------------------------------------

    def _docs(self, conn: Conn, client_id: str, where: str, params: tuple[Any, ...]) -> list[Doc]:
        rows = conn.execute(
            f"SELECT id, direction, invoice FROM documents d WHERE d.client_id = %s AND d.superseded_by IS NULL AND {where} ORDER BY d.id",
            (client_id, *params),
        ).fetchall()
        return [Doc(r["id"], r["direction"], Invoice.from_json(r["invoice"])) for r in rows]

    def _duplicate_doc_ids(self, conn: Conn, client_id: str) -> set[int]:
        rows = conn.execute(
            """SELECT d.id FROM documents d WHERE d.client_id = %s AND d.invoice_no IS NOT NULL AND d.superseded_by IS NULL AND EXISTS (
                 SELECT 1 FROM documents o WHERE o.client_id = d.client_id AND o.id < d.id AND o.invoice_no = d.invoice_no
                 AND lower(o.seller_name) = lower(d.seller_name) AND o.direction = d.direction AND o.superseded_by IS NULL)""",
            (client_id,),
        ).fetchall()
        return {r["id"] for r in rows}

    def run(self, conn: Conn, client_id: str, period: str, actor: Principal) -> dict[str, Any]:
        status = conn.execute(
            "SELECT status FROM closes WHERE client_id = %s AND period = %s", (client_id, period)
        ).fetchone()
        if status and status["status"] == "festgeschrieben":
            raise CloseError("Der Monat ist festgeschrieben")
        conn.execute(
            "INSERT INTO closes (client_id, period, status) VALUES (%s, %s, 'in_arbeit') ON CONFLICT (client_id, period) DO UPDATE SET status = 'in_arbeit'",
            (client_id, period),
        )
        ctx = self.context(conn, client_id, period)
        cc = ctx.close
        start, end = ctx.period_start, ctx.period_end
        dups = self._duplicate_doc_ids(conn, client_id)
        created = {"payment": 0, "invoice": 0}

        # 1. OPOS: invoices of the month are booked on receipt - the way this firm does it for this
        #    partner. Partners the firm books straight from the bank, and till receipts, are not.
        if ctx.client.booking_method == "opos":
            fresh = self._docs(
                conn,
                client_id,
                """d.period = %s AND NOT EXISTS (SELECT 1 FROM items i WHERE i.kind = 'invoice' AND i.document_ids[1] = d.id)
                   AND NOT EXISTS (SELECT 1 FROM items i WHERE i.kind = 'payment' AND d.id = ANY(i.document_ids))""",
                (period,),
            )
            paid = self._paid_at_once(conn, ctx, period, fresh)
            for d in fresh:
                if d.id in paid or not self._books_on_receipt(ctx, d):
                    continue
                p = propose_invoice(ctx, d)
                if d.id in dups:
                    p.flags.append("duplicate_invoice")
                    p.route = "review"
                self._create_item(conn, ctx, period, "invoice", None, [d.id], p, actor)
                created["invoice"] += 1

        # 2. Payments: match to documents not yet settled by a payment.
        txs = [
            Tx(
                r["id"],
                r["booking_date"],
                r["amount_cents"],
                r["counterparty_name"],
                r["counterparty_iban"],
                r["remittance"],
            )
            for r in conn.execute(
                """SELECT * FROM transactions t WHERE t.client_id = %s AND t.period = %s
                   AND NOT EXISTS (SELECT 1 FROM items i WHERE i.transaction_id = t.id) ORDER BY booking_date, id""",
                (client_id, period),
            ).fetchall()
        ]
        lo, hi = start - timedelta(days=cc.window_days_before), end + timedelta(days=cc.window_days_after)
        open_docs = self._docs(
            conn,
            client_id,
            """coalesce(d.issue_date, d.received_at::date) BETWEEN %s AND %s
               AND NOT EXISTS (SELECT 1 FROM items i WHERE i.kind = 'payment' AND d.id = ANY(i.document_ids))""",
            (lo, hi),
        )
        open_docs = [d for d in open_docs if d.id not in dups]
        cleared = self._cleared(conn, client_id) if ctx.client.booking_method == "opos" else {}
        matches = match(txs, open_docs, cc, ctx.tax)
        by_id = {d.id: d for d in open_docs}
        items = self.open_items(conn, ctx) if ctx.client.booking_method == "opos" else []
        for tx in txs:
            m = matches.get(tx.id)
            docs = [by_id[i] for i in m.doc_ids] if m else []
            hit = match_open_item(ctx, tx, items) if (not docs and items) else None
            if hit:
                p = propose_open_item(ctx, tx, hit[0], hit[1])
                hit[0].balance_cents = 0  # one payment per open item in this run
            else:
                p = propose_payment(ctx, tx, docs, m, cleared=cleared)
            self._create_item(conn, ctx, period, "payment", tx.id, [d.id for d in docs], p, actor)
            created["payment"] += 1

        # 3. Held items that a newly arrived document may resolve (receipt sent by mail or portal).
        used = {i for m in matches.values() for i in m.doc_ids}
        rest = [d for d in open_docs if d.id not in used]
        revived = self._revive(conn, ctx, period, rest, cleared, actor) if rest else 0

        summary = self._summary(conn, client_id, period)
        summary.update({"created": created, "revived": revived})
        bundle = self._ask_client(conn, ctx, period, actor)
        if bundle:
            summary["query"] = bundle
        conn.execute(
            "UPDATE closes SET last_run_at = now(), run_summary = %s WHERE client_id = %s AND period = %s",
            (Jsonb({k: v for k, v in summary.items() if k != "query"}), client_id, period),
        )
        event(
            conn,
            actor.login,
            "close.run",
            {"period": period, **{k: v for k, v in summary.items() if k != "query"}},
            firm=ctx.client.firm_id,
            client=client_id,
        )
        return summary

    def _paid_at_once(self, conn: Conn, ctx: Context, period: str, docs: list[Doc]) -> set[int]:
        """Invoices of partners without a personal account that this month's bank shows paid
        within a few days of their date (card, immediate transfer): booked with the payment."""
        if not docs:
            return set()
        txs = [
            Tx(
                r["id"],
                r["booking_date"],
                r["amount_cents"],
                r["counterparty_name"],
                r["counterparty_iban"],
                r["remittance"],
            )
            for r in conn.execute(
                """SELECT * FROM transactions t WHERE t.client_id = %s AND t.period = %s
                   AND NOT EXISTS (SELECT 1 FROM items i WHERE i.transaction_id = t.id)""",
                (ctx.client.id, period),
            ).fetchall()
        ]
        by_id = {d.id: d for d in docs}
        out: set[int] = set()
        for tx_id, m in match(txs, docs, ctx.close, ctx.tax).items():
            tx = next(t for t in txs if t.id == tx_id)
            for doc_id in m.doc_ids:
                d = by_id[doc_id]
                inv = d.invoice
                incoming = d.direction == "in"
                party = inv.seller if incoming else inv.buyer
                known = ctx.find_counterparty(
                    "kreditor" if incoming else "debitor",
                    iban=inv.seller_iban if incoming else None,
                    vat_id=party.vat_id,
                    name=party.name,
                )
                issued = inv.issue_date or tx.on
                if known is None and (tx.on - issued).days <= ctx.close.opos_paid_within_days:
                    out.add(doc_id)
        return out

    def _books_on_receipt(self, ctx: Context, d: Doc) -> bool:
        inv = d.invoice
        incoming = d.direction == "in"
        party = inv.seller if incoming else inv.buyer
        kind = "kreditor" if incoming else "debitor"
        if ctx.find_counterparty(
            kind, iban=inv.seller_iban if incoming else None, vat_id=party.vat_id, name=party.name
        ):
            return True
        hit = ctx.memory.lookup(inv.seller_iban if incoming else None, party.name, money_in=not incoming)
        if hit is not None and hit.uses >= ctx.close.memory_min_uses:
            return hit.personal_share >= 0.5
        small = (inv.gross_cents or 0) <= ctx.tax.kleinbetrag_gross_cents
        return not (incoming and small)

    def open_items(self, conn: Conn, ctx: Context) -> list[OpenItem]:
        """Unsettled invoices on personal accounts, from the booked journal (history included)."""
        ch = ctx.chart
        rows = conn.execute(
            "SELECT debit, credit, amount_cents, tax, doc_ref FROM bookings WHERE client_id = %s AND doc_ref <> ''",
            (ctx.client.id,),
        ).fetchall()
        bal: dict[tuple[int, str], int] = defaultdict(int)
        rate: dict[tuple[int, str], tuple[int, int]] = {}
        for r in rows:
            for acct, sign in ((r["debit"], 1), (r["credit"], -1)):
                if not ch.is_personal(acct):
                    continue
                key = (acct, r["doc_ref"])
                bal[key] += sign * r["amount_cents"]
                other = r["credit"] if sign == 1 else r["debit"]
                if not ch.is_personal(other) and r["tax"] in ("V19", "V7", "U19", "U7"):
                    prev = rate.get(key, (0, 19))
                    if r["amount_cents"] > prev[0]:
                        rate[key] = (r["amount_cents"], int(r["tax"][1:]))
        names = {c.account: c for c in ctx.counterparties}
        out = []
        for (acct, ref), b in bal.items():
            kind = "kreditor" if ch.is_creditor(acct) else "debitor"
            outstanding = -b if kind == "kreditor" else b
            if outstanding > 0:
                cp = names.get(acct)
                out.append(
                    OpenItem(
                        kind,
                        acct,
                        ref,
                        outstanding,
                        rate.get((acct, ref), (0, 19))[1],
                        cp.name if cp else "",
                        cp.iban if cp else None,
                    )
                )
        return out

    def _cleared(self, conn: Conn, client_id: str) -> dict[int, int]:
        rows = conn.execute(
            "SELECT document_ids[1] AS doc, proposal AS p FROM items WHERE client_id = %s AND kind = 'invoice' AND coalesce(decision, '') <> 'dismissed'",
            (client_id,),
        ).fetchall()
        out: dict[int, int] = {}
        for r in rows:
            acct = (r["p"].get("counterparty") or {}).get("account")
            if acct:
                out[int(r["doc"])] = int(acct)
        return out

    def _revive(
        self, conn: Conn, ctx: Context, period: str, docs: list[Doc], cleared: dict[int, int], actor: Principal
    ) -> int:
        rows = conn.execute(
            """SELECT i.id, t.id AS tx, t.booking_date, t.amount_cents, t.counterparty_name, t.counterparty_iban, t.remittance
               FROM items i JOIN transactions t ON t.id = i.transaction_id
               WHERE i.client_id = %s AND i.period = %s AND i.state = 'client' AND cardinality(i.document_ids) = 0
               AND (i.proposal -> 'flags') ?| array['missing_receipt', 'invoice_incomplete']""",
            (ctx.client.id, period),
        ).fetchall()
        if not rows:
            return 0
        txs = [
            Tx(
                r["tx"],
                r["booking_date"],
                r["amount_cents"],
                r["counterparty_name"],
                r["counterparty_iban"],
                r["remittance"],
            )
            for r in rows
        ]
        ms = match(txs, docs, ctx.close, ctx.tax)
        by_doc = {d.id: d for d in docs}
        n = 0
        for r, tx in zip(rows, txs, strict=True):
            m = ms.get(tx.id)
            if not m:
                continue
            ds = [by_doc[i] for i in m.doc_ids]
            p = propose_payment(ctx, tx, ds, m, cleared=cleared)
            p.reasons.insert(0, Reason("receipt_arrived", "Beleg nachgereicht"))
            self._update_item(conn, ctx, r["id"], [d.id for d in ds], p, actor, decision_if_booked="auto")
            n += 1
        return n

    def _create_item(
        self,
        conn: Conn,
        ctx: Context,
        period: str,
        kind: str,
        tx_id: int | None,
        doc_ids: list[int],
        p: Proposal,
        actor: Principal,
    ) -> int:
        state = {"auto": "auto", "review": "review", "client": "client"}[p.route]
        item_id: int = need(
            conn.execute(
                """INSERT INTO items (client_id, period, kind, transaction_id, document_ids, state, proposal)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (ctx.client.id, period, kind, tx_id, doc_ids, state, Jsonb(p.to_json())),
            ).fetchone()
        )["id"]
        if p.route == "auto":
            self._book(
                conn, ctx, item_id, period, p.lines, origin="auto", decision="auto", actor=actor, doc_ids=doc_ids
            )
        return item_id

    def _update_item(
        self,
        conn: Conn,
        ctx: Context,
        item_id: int,
        doc_ids: list[int],
        p: Proposal,
        actor: Principal,
        *,
        decision_if_booked: str,
    ) -> None:
        state = {"auto": "auto", "review": "review", "client": "client"}[p.route]
        conn.execute(
            "UPDATE items SET document_ids = %s, state = %s, proposal = %s, updated_at = now() WHERE id = %s",
            (doc_ids, state, Jsonb(p.to_json()), item_id),
        )
        if p.route == "auto":
            period = need(conn.execute("SELECT period FROM items WHERE id = %s", (item_id,)).fetchone())["period"]
            origin = "client" if decision_if_booked == "client" else "auto"
            self._book(
                conn,
                ctx,
                item_id,
                period,
                p.lines,
                origin=origin,
                decision=decision_if_booked,
                actor=actor,
                doc_ids=doc_ids,
            )

    def _book(
        self,
        conn: Conn,
        ctx: Context,
        item_id: int,
        period: str,
        lines: list[Line],
        *,
        origin: str,
        decision: str,
        actor: Principal,
        doc_ids: list[int],
    ) -> None:
        for ln in lines:
            conn.execute(
                """INSERT INTO bookings (client_id, period, booking_date, amount_cents, debit, credit, tax, text, doc_ref, family, role,
                   item_id, document_id, origin) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ctx.client.id,
                    period,
                    ln.date,
                    ln.amount_cents,
                    ln.debit,
                    ln.credit,
                    ln.tax,
                    ln.text,
                    ln.doc_ref,
                    ln.family,
                    ln.role,
                    item_id,
                    doc_ids[0] if doc_ids else None,
                    origin,
                ),
            )
        state = "parked" if decision == "parked" else ("auto" if decision == "auto" else "done")
        conn.execute(
            "UPDATE items SET state = %s, final = %s, decision = %s, decided_by = %s, decided_at = now(), updated_at = now() WHERE id = %s",
            (state, Jsonb({"lines": [ln.to_json() for ln in lines]}), decision, actor.login, item_id),
        )
        # A new supplier or customer accepted with the item becomes master data.
        prop = need(
            conn.execute("SELECT proposal -> 'counterparty' AS cp FROM items WHERE id = %s", (item_id,)).fetchone()
        )["cp"]
        if prop and prop.get("new") and prop.get("account"):
            conn.execute(
                """INSERT INTO counterparties (client_id, kind, account, name, norm_name, iban, vat_id, country, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'engine') ON CONFLICT (client_id, account) DO NOTHING""",
                (
                    ctx.client.id,
                    prop["kind"],
                    prop["account"],
                    prop["name"],
                    normalize_name(prop["name"]),
                    prop.get("iban"),
                    prop.get("vat_id"),
                    prop.get("country"),
                ),
            )

    def _summary(self, conn: Conn, client_id: str, period: str) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT state, decision, count(*) AS n FROM items WHERE client_id = %s AND period = %s GROUP BY state, decision",
            (client_id, period),
        ).fetchall()
        by_state: dict[str, int] = defaultdict(int)
        by_decision: dict[str, int] = defaultdict(int)
        for r in rows:
            by_state[r["state"]] += r["n"]
            if r["decision"]:
                by_decision[r["decision"]] += r["n"]
        total = sum(by_state.values())
        return {"items": total, "states": dict(by_state), "decisions": dict(by_decision)}

    # --- client questions --------------------------------------------------------------------

    def _ask_client(self, conn: Conn, ctx: Context, period: str, actor: Principal) -> dict[str, Any] | None:
        rows = conn.execute(
            """SELECT i.id, i.proposal, i.document_ids, t.booking_date, t.amount_cents, t.counterparty_name
               FROM items i LEFT JOIN transactions t ON t.id = i.transaction_id
               WHERE i.client_id = %s AND i.period = %s AND i.state = 'client'
               AND NOT EXISTS (SELECT 1 FROM query_items qi JOIN queries qq ON qq.id = qi.query_id
                               WHERE qi.item_id = i.id AND qi.answer IS NULL AND qq.status = 'offen')
               ORDER BY t.booking_date NULLS LAST, i.id""",
            (ctx.client.id, period),
        ).fetchall()
        if not rows:
            return None
        cfg = close_config()
        token = secrets.token_urlsafe(24)
        due = date.today() + timedelta(days=cfg.answer_days)
        texts: list[str] = []
        prepared = []
        for r in rows:
            prop = Proposal.from_json(r["proposal"])
            reason = next(f for f in prop.flags if f in CLIENT_FLAGS)
            details = ""
            if reason == "invoice_incomplete" and r["document_ids"]:
                inv = Invoice.from_json(
                    need(
                        conn.execute("SELECT invoice FROM documents WHERE id = %s", (r["document_ids"][0],)).fetchone()
                    )["invoice"]
                )
                details = ", ".join(LABELS.get(f, f) for f in missing_fields(inv, ctx.tax))
            on = r["booking_date"] or ctx.period_start
            amount = r["amount_cents"] if r["amount_cents"] is not None else -sum(ln.amount_cents for ln in prop.lines)
            text = q.question_for(
                reason,
                on=on,
                amount_cents=amount,
                counterparty=r["counterparty_name"] or prop.counterparty.get("name", ""),
                details=details,
            )
            texts.append(text)
            prepared.append((r["id"], reason, text))
        firm = conn.execute("SELECT f.name FROM firms f WHERE f.id = %s", (ctx.client.firm_id,)).fetchone()
        contact = conn.execute(
            "SELECT contact_name, contact_email FROM clients WHERE id = %s", (ctx.client.id,)
        ).fetchone()
        link = f"{settings().public_url.rstrip('/')}/portal/{token}"
        subject, body = q.bundle_message(
            client_name=ctx.client.name,
            contact_name=contact["contact_name"] if contact else "",
            firm_name=firm["name"] if firm else "",
            period=period,
            questions=texts,
            link=link,
            due=due,
        )
        qid = need(
            conn.execute(
                "INSERT INTO queries (client_id, period, token_hash, subject, message, due_on) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (ctx.client.id, period, sha256(token.encode()), subject, body, due),
            ).fetchone()
        )["id"]
        for item_id, reason, text in prepared:
            conn.execute(
                "INSERT INTO query_items (query_id, client_id, item_id, reason, question, options) VALUES (%s,%s,%s,%s,%s,%s)",
                (qid, ctx.client.id, item_id, reason, text, Jsonb(q.OPTIONS[reason])),
            )
        if contact and contact["contact_email"]:
            conn.execute(
                "INSERT INTO outbox (client_id, to_email, subject, body) VALUES (%s,%s,%s,%s)",
                (ctx.client.id, contact["contact_email"], subject, body),
            )
        event(
            conn,
            actor.login,
            "query.sent",
            {"query": qid, "items": len(prepared)},
            firm=ctx.client.firm_id,
            client=ctx.client.id,
        )
        return {"id": qid, "token": token, "items": len(prepared), "subject": subject}

    def apply_answers(self, conn: Conn, client_id: str, period: str, actor: Principal) -> int:
        """Turns answered questions into bookings (rules) or review items."""
        rows = conn.execute(
            """SELECT qi.id AS qi, qi.item_id, qi.reason, qi.answer, qi.query_id, i.kind, i.document_ids, t.id AS tx, t.booking_date,
                      t.amount_cents, t.counterparty_name, t.counterparty_iban, t.remittance
               FROM query_items qi JOIN items i ON i.id = qi.item_id LEFT JOIN transactions t ON t.id = i.transaction_id
               WHERE qi.client_id = %s AND i.period = %s AND qi.answer IS NOT NULL AND i.state = 'client'""",
            (client_id, period),
        ).fetchall()
        if not rows:
            return 0
        ctx = self.context(conn, client_id, period)
        cleared = self._cleared(conn, client_id) if ctx.client.booking_method == "opos" else {}
        # One decision per item: all its answers together, the later ones winning.
        by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for r in sorted(rows, key=lambda x: x["qi"]):
            by_item[r["item_id"]].append(dict(r))
        n = 0
        for item_id, group in by_item.items():
            state = conn.execute(
                "SELECT state, document_ids FROM items WHERE id = %s FOR UPDATE", (item_id,)
            ).fetchone()
            if state is None or state["state"] != "client":
                continue
            r = group[-1]
            ans: dict[str, Any] = {}
            for g in group:
                ans.update(q.answers_for(g["reason"], g["answer"]))
            doc_ids = list(state["document_ids"])
            uploaded = [int(g["answer"]["document_id"]) for g in group if g["answer"].get("document_id")]
            if uploaded:
                new_id = uploaded[-1]
                if doc_ids and new_id not in doc_ids:
                    # A corrected invoice replaces the incomplete one (both stay archived).
                    conn.execute(
                        "UPDATE documents SET superseded_by = %s WHERE id = ANY(%s) AND id <> %s",
                        (new_id, doc_ids, new_id),
                    )
                doc_ids = [new_id]
            docs = self._docs(conn, client_id, "d.id = ANY(%s)", (doc_ids,)) if doc_ids else []
            if ans.get("invoice_no") and not docs:
                docs = self._docs(
                    conn, client_id, "d.direction = 'out' AND upper(d.invoice_no) = upper(%s)", (ans["invoice_no"],)
                )
                doc_ids = [d.id for d in docs]
            if r["kind"] == "invoice":
                p = propose_invoice(ctx, docs[0], answers=ans) if docs else None
            else:
                tx = Tx(
                    r["tx"],
                    r["booking_date"],
                    r["amount_cents"],
                    r["counterparty_name"],
                    r["counterparty_iban"],
                    r["remittance"],
                )
                m = Match(tx.id, doc_ids, 1.0, reasons=["vom Mandanten zugeordnet"]) if docs else None
                p = propose_payment(ctx, tx, docs, m, answers=ans, cleared=cleared)
            if p is None:
                continue
            for g in reversed(group):
                p.reasons.insert(
                    0, Reason("client_answer", "Antwort des Mandanten: " + _answer_text(g["reason"], g["answer"]))
                )
            if ans.get("needs_review") and p.route == "auto":
                p.flags.append("client_answer")
                p.route = "review"
            self._update_item(conn, ctx, item_id, doc_ids, p, actor, decision_if_booked="client")
            n += 1
        conn.execute(
            """UPDATE queries SET status = 'geschlossen' WHERE client_id = %s AND period = %s AND status <> 'geschlossen'
               AND NOT EXISTS (SELECT 1 FROM query_items qi JOIN items i ON i.id = qi.item_id WHERE qi.query_id = queries.id AND i.state = 'client')""",
            (client_id, period),
        )
        event(
            conn,
            actor.login,
            "query.applied",
            {"period": period, "items": n},
            firm=ctx.client.firm_id,
            client=client_id,
        )
        return n

    # --- staff decisions ---------------------------------------------------------------------

    def _item(self, conn: Conn, item_id: int) -> dict[str, Any]:
        r = conn.execute("SELECT * FROM items WHERE id = %s FOR UPDATE", (item_id,)).fetchone()
        if r is None:
            raise CloseError("Posten nicht gefunden")
        return dict(r)

    def accept(self, conn: Conn, item_id: int, actor: Principal) -> None:
        it = self._item(conn, item_id)
        if it["state"] != "review":
            raise CloseError("Nur Posten in Prüfung können übernommen werden")
        p = Proposal.from_json(it["proposal"])
        if any(f in CLIENT_FLAGS for f in p.flags):
            raise CloseError("Dieser Posten wartet auf den Mandanten")
        ctx = self.context(conn, it["client_id"], it["period"])
        self._book(
            conn,
            ctx,
            item_id,
            it["period"],
            p.lines,
            origin="review",
            decision="accepted",
            actor=actor,
            doc_ids=list(it["document_ids"]),
        )
        event(conn, actor.login, "item.accept", {"item": item_id}, firm=ctx.client.firm_id, client=it["client_id"])

    def correct(
        self, conn: Conn, item_id: int, actor: Principal, *, family: str, tax: str | None = None, reason: str = ""
    ) -> Proposal:
        it = self._item(conn, item_id)
        if it["state"] not in ("review", "client"):
            raise CloseError("Dieser Posten ist bereits gebucht")
        if family not in families():
            raise CloseError("Unbekannte Buchungsfamilie")
        old = Proposal.from_json(it["proposal"])
        ctx = self.context(conn, it["client_id"], it["period"])
        docs = (
            self._docs(conn, it["client_id"], "d.id = ANY(%s)", (list(it["document_ids"]),))
            if it["document_ids"]
            else []
        )
        answers = {"meals_details": True, "receipt": "no_receipt" if not docs else None}
        if it["kind"] == "invoice":
            p = propose_invoice(ctx, docs[0], force_family=family, force_tax=tax, answers=answers)
        else:
            t = conn.execute("SELECT * FROM transactions WHERE id = %s", (it["transaction_id"],)).fetchone()
            assert t is not None
            tx = Tx(
                t["id"],
                t["booking_date"],
                t["amount_cents"],
                t["counterparty_name"],
                t["counterparty_iban"],
                t["remittance"],
            )
            m = Match(tx.id, list(it["document_ids"]), 1.0) if docs else None
            cleared = self._cleared(conn, it["client_id"]) if ctx.client.booking_method == "opos" else {}
            p = propose_payment(ctx, tx, docs, m, force_family=family, force_tax=tax, answers=answers, cleared=cleared)
        blocking = [f for f in p.flags if f in ("no_account",)]
        if blocking:
            raise CloseError(REVIEW_FLAGS[blocking[0]])
        p.reasons.insert(0, Reason("corrected", f"Korrigiert von {actor.name}" + (f": {reason}" if reason else "")))
        conn.execute("UPDATE items SET proposal = %s WHERE id = %s", (Jsonb(p.to_json()), item_id))
        self._book(
            conn,
            ctx,
            item_id,
            it["period"],
            p.lines,
            origin="review",
            decision="corrected",
            actor=actor,
            doc_ids=list(it["document_ids"]),
        )
        conn.execute(
            """INSERT INTO corrections (firm_id, client_id, item_id, login, from_family, to_family, from_tax, to_tax, reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ctx.client.firm_id, it["client_id"], item_id, actor.login, old.family, family, old.tax, p.tax, reason),
        )
        event(
            conn,
            actor.login,
            "item.correct",
            {"item": item_id, "from": old.family, "to": family, "tax": p.tax},
            firm=ctx.client.firm_id,
            client=it["client_id"],
        )
        return p

    def book_manual(self, conn: Conn, item_id: int, actor: Principal, lines: list[Line], reason: str = "") -> None:
        """Staff enter the booking themselves. Lines must balance the payment it explains."""
        it = self._item(conn, item_id)
        if it["state"] not in ("review", "client"):
            raise CloseError("Dieser Posten ist bereits gebucht")
        ctx = self.context(conn, it["client_id"], it["period"])
        if not lines or any(ln.amount_cents <= 0 for ln in lines):
            raise CloseError("Buchungszeilen mit positiven Beträgen angeben")
        if it["kind"] == "payment":
            t = conn.execute("SELECT amount_cents FROM transactions WHERE id = %s", (it["transaction_id"],)).fetchone()
            assert t is not None
            bank = ctx.chart.system["bank"]
            moved = sum(ln.amount_cents for ln in lines if ln.debit == bank) - sum(
                ln.amount_cents for ln in lines if ln.credit == bank
            )
            if moved != t["amount_cents"]:
                raise CloseError("Die Buchung muss den Bankbetrag genau abbilden")
        old = Proposal.from_json(it["proposal"])
        self._book(
            conn,
            ctx,
            item_id,
            it["period"],
            lines,
            origin="manual",
            decision="corrected",
            actor=actor,
            doc_ids=list(it["document_ids"]),
        )
        fam = next((ln.family for ln in lines if ln.family), None)
        conn.execute(
            """INSERT INTO corrections (firm_id, client_id, item_id, login, from_family, to_family, from_tax, to_tax, reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                ctx.client.firm_id,
                it["client_id"],
                item_id,
                actor.login,
                old.family,
                fam,
                old.tax,
                lines[0].tax,
                reason or "manuell",
            ),
        )
        event(
            conn,
            actor.login,
            "item.manual",
            {"item": item_id, "lines": len(lines)},
            firm=ctx.client.firm_id,
            client=it["client_id"],
        )

    def dismiss(self, conn: Conn, item_id: int, actor: Principal, note: str) -> None:
        """An incoming document that is not an invoice to book on receipt (paid at once, a copy):
        it stays archived and is booked with its payment."""
        it = self._item(conn, item_id)
        if it["kind"] != "invoice" or it["state"] not in ("review", "client"):
            raise CloseError("Nur offene Rechnungseingänge können verworfen werden")
        conn.execute(
            "UPDATE items SET state = 'done', decision = 'dismissed', decided_by = %s, decided_at = now(), updated_at = now() WHERE id = %s",
            (actor.login, item_id),
        )
        client = self.profile(conn, it["client_id"])
        event(
            conn,
            actor.login,
            "item.dismiss",
            {"item": item_id, "note": note[:200]},
            firm=client.firm_id,
            client=it["client_id"],
        )

    def park(self, conn: Conn, item_id: int, actor: Principal, note: str) -> None:
        """Books a payment nobody can explain yet to the suspense account, so the bank reconciles."""
        it = self._item(conn, item_id)
        if it["state"] not in ("review", "client"):
            raise CloseError("Dieser Posten ist bereits gebucht")
        if it["kind"] != "payment":
            raise CloseError("Nur Zahlungen können auf das Klärungskonto")
        ctx = self.context(conn, it["client_id"], it["period"])
        t = conn.execute("SELECT * FROM transactions WHERE id = %s", (it["transaction_id"],)).fetchone()
        assert t is not None
        bank, sus = ctx.chart.system["bank"], ctx.chart.system["suspense"]
        amt = abs(t["amount_cents"])
        debit, credit = (bank, sus) if t["amount_cents"] > 0 else (sus, bank)
        line = Line(
            t["booking_date"],
            amt,
            debit,
            credit,
            "NONE",
            (t["counterparty_name"] or "Klärung")[:60],
            "suspense",
            None,
            "",
        )
        self._book(
            conn,
            ctx,
            item_id,
            it["period"],
            [line],
            origin="manual",
            decision="parked",
            actor=actor,
            doc_ids=list(it["document_ids"]),
        )
        event(
            conn,
            actor.login,
            "item.park",
            {"item": item_id, "note": note[:200]},
            firm=ctx.client.firm_id,
            client=it["client_id"],
        )

    # --- VAT return, sign-off, export ----------------------------------------------------------

    def _is_tax_account(self, ch: Chart) -> Callable[[int], bool]:
        system = set(ch.system.values())

        def f(acct: int) -> bool:
            return acct not in system and not ch.is_personal(acct)

        return f

    def _lines(self, conn: Conn, client_id: str, periods: list[str]) -> dict[str, list[Line]]:
        rows = conn.execute(
            "SELECT period, booking_date, amount_cents, debit, credit, tax, text, family, role, doc_ref FROM bookings WHERE client_id = %s AND period = ANY(%s)",
            (client_id, periods),
        ).fetchall()
        out: dict[str, list[Line]] = defaultdict(list)
        for r in rows:
            out[r["period"]].append(
                Line(
                    r["booking_date"],
                    r["amount_cents"],
                    r["debit"],
                    r["credit"],
                    r["tax"],
                    r["text"],
                    r["family"],
                    r["role"],
                    r["doc_ref"],
                )
            )
        return out

    def ustva(self, conn: Conn, client_id: str, period: str) -> dict[str, Any]:
        client = self.profile(conn, client_id)
        ch = self.chart_for(conn, client.firm_id, client.chart)
        cfg, cc = tax_config(), close_config()
        hist_periods = prev_periods(period, cc.plaus_months)
        lines = self._lines(conn, client_id, [period, *hist_periods])
        is_tax = self._is_tax_account(ch)
        rows = ustva_mod.compute(lines.get(period, []), cfg, is_tax)
        as_dict = {r.kz: {"base_cents": r.base_cents, "tax_cents": r.tax_cents} for r in rows.values()}
        history = []
        for hp in hist_periods:
            if lines.get(hp):
                h = ustva_mod.compute(lines[hp], cfg, is_tax)
                history.append({r.kz: {"base_cents": r.base_cents, "tax_cents": r.tax_cents} for r in h.values()})
        flags = plausibility_check(as_dict, history, cc, cfg.kennzahl_labels)
        _start, end = period_bounds(period)
        due = _due_date(end, cfg.due_day, cfg.dauerfrist_extra_months if client.dauerfrist else 0)
        quarterly = client.vat_period == "quartal"
        return {
            "period": period,
            "rows": ustva_mod.to_json(rows),
            "flags": [{"kz": f.kz, "text": f.text} for f in flags],
            "due_on": due.isoformat(),
            "quarterly": quarterly,
            "files_this_month": client.vat_regime not in ("klein", "befreit")
            and ((not quarterly) or end.month in (3, 6, 9, 12)),
            "history_months": len(history),
            "kleinunternehmer": client.vat_regime == "klein",
        }

    def checks(self, conn: Conn, client_id: str, period: str) -> dict[str, Any]:
        client = self.profile(conn, client_id)
        ch = self.chart_for(conn, client.firm_id, client.chart)
        bank = ch.system["bank"]
        open_items = conn.execute(
            "SELECT state, count(*) AS n FROM items WHERE client_id = %s AND period = %s AND state IN ('review', 'client') GROUP BY state",
            (client_id, period),
        ).fetchall()
        tx_sum = need(
            conn.execute(
                "SELECT coalesce(sum(amount_cents), 0) AS s FROM transactions WHERE client_id = %s AND period = %s",
                (client_id, period),
            ).fetchone()
        )["s"]
        bank_sum = need(
            conn.execute(
                """SELECT coalesce(sum(CASE WHEN debit = %s THEN amount_cents ELSE 0 END) - sum(CASE WHEN credit = %s THEN amount_cents ELSE 0 END), 0) AS s
               FROM bookings WHERE client_id = %s AND period = %s AND origin <> 'import'""",
                (bank, bank, client_id, period),
            ).fetchone()
        )["s"]
        open_by = {r["state"]: r["n"] for r in open_items}
        return {
            "open_review": open_by.get("review", 0),
            "open_client": open_by.get("client", 0),
            "bank_reconciled": int(tx_sum) == int(bank_sum),
            "bank_difference_cents": int(tx_sum) - int(bank_sum),
        }

    def sign_off(
        self, conn: Conn, client_id: str, period: str, actor: Principal, *, acknowledge_flags: bool
    ) -> dict[str, Any]:
        if not actor.can_sign_off:
            raise CloseError("Nur die Steuerberaterin oder der Steuerberater gibt den Monat frei")
        st = conn.execute(
            "SELECT status FROM closes WHERE client_id = %s AND period = %s FOR UPDATE", (client_id, period)
        ).fetchone()
        if st is None:
            raise CloseError("Für diesen Monat wurde noch kein Abschluss gestartet")
        if st["status"] == "festgeschrieben":
            raise CloseError("Der Monat ist bereits festgeschrieben")
        c = self.checks(conn, client_id, period)
        if c["open_review"] or c["open_client"]:
            raise CloseError(f"Noch offen: {c['open_review']} in Prüfung, {c['open_client']} beim Mandanten")
        if not c["bank_reconciled"]:
            raise CloseError(f"Bank nicht abgestimmt (Differenz {c['bank_difference_cents'] / 100:.2f} €)")
        u = self.ustva(conn, client_id, period)
        if u["flags"] and not acknowledge_flags:
            raise CloseError("Auffälligkeiten in der Umsatzsteuer bitte bestätigen")
        conn.execute(
            "UPDATE bookings SET locked = true WHERE client_id = %s AND period = %s AND NOT locked", (client_id, period)
        )
        filename, data = self.export(conn, client_id, period, locked=True)
        digest = sha256(data)
        self.store.put(f"{client_id}/exports/{period}/{digest}.csv", data, "text/csv")
        conn.execute(
            """UPDATE closes SET status = 'festgeschrieben', ustva = %s, flags = %s, signed_by = %s, signed_at = now(), export_sha256 = %s
               WHERE client_id = %s AND period = %s""",
            (Jsonb(u), Jsonb(u["flags"]), actor.login, digest, client_id, period),
        )
        client = self.profile(conn, client_id)
        event(
            conn,
            actor.login,
            "close.sign_off",
            {
                "period": period,
                "export_sha256": digest,
                "kz83_cents": next((r["tax_cents"] for r in u["rows"] if r["kz"] == "83"), 0),
            },
            firm=client.firm_id,
            client=client_id,
        )
        return {"export": filename, "sha256": digest, "ustva": u}

    def export(self, conn: Conn, client_id: str, period: str, *, locked: bool | None = None) -> tuple[str, bytes]:
        client = self.profile(conn, client_id)
        ch = self.chart_for(conn, client.firm_id, client.chart)
        is_tax = self._is_tax_account(ch)
        start, end = period_bounds(period)
        if locked is None:
            st = conn.execute(
                "SELECT status FROM closes WHERE client_id = %s AND period = %s", (client_id, period)
            ).fetchone()
            locked = bool(st and st["status"] == "festgeschrieben")
        rows = conn.execute(
            "SELECT * FROM bookings WHERE client_id = %s AND period = %s AND origin <> 'import' ORDER BY booking_date, id",
            (client_id, period),
        ).fetchall()
        out: list[ExtfBooking] = []
        for r in rows:
            debit, credit = r["debit"], r["credit"]
            # The tax-bearing account goes into Gegenkonto, where DATEV applies the BU key.
            if is_tax(debit) and not is_tax(credit):
                konto, gegen, sh = credit, debit, "H"
            else:
                konto, gegen, sh = debit, credit, "S"
            out.append(
                ExtfBooking(
                    amount_cents=r["amount_cents"],
                    sh=sh,
                    konto=konto,
                    gegenkonto=gegen,
                    bu=ch.bu_key(gegen, r["tax"]),
                    belegdatum=max(min(r["booking_date"], end), start),
                    belegfeld1=r["doc_ref"],
                    buchungstext=r["text"],
                )
            )
        fy_start = date(
            start.year if start.month >= client.fiscal_year_start_month else start.year - 1,
            client.fiscal_year_start_month,
            1,
        )
        data = write_buchungsstapel(
            out,
            berater=client.berater_nr,
            mandant=client.mandant_nr,
            fiscal_year_start=fy_start,
            length=ch.length,
            date_from=start,
            date_to=end,
            label=f"Monatsabschluss {start.strftime('%m/%Y')}",
            chart_code=ch.name[-2:],
            locked=locked,
            created=datetime.now(),
        )
        return f"EXTF_Buchungsstapel_{client.mandant_nr}_{period}.csv", data

    def export_master(self, conn: Conn, client_id: str) -> tuple[str, bytes]:
        """New suppliers and customers the agent created, as DATEV master data."""
        client = self.profile(conn, client_id)
        ch = self.chart_for(conn, client.firm_id, client.chart)
        rows = conn.execute(
            "SELECT * FROM counterparties WHERE client_id = %s AND created_by = 'engine' ORDER BY account", (client_id,)
        ).fetchall()
        recs = [MasterRecord(r["account"], r["name"], r["vat_id"], r["country"], iban=r["iban"]) for r in rows]
        data = write_stammdaten(
            recs,
            berater=client.berater_nr,
            mandant=client.mandant_nr,
            fiscal_year_start=date(date.today().year, client.fiscal_year_start_month, 1),
            length=ch.length,
        )
        return f"EXTF_Stammdaten_{client.mandant_nr}.csv", data


def _due_date(period_end: date, day: int, extra_months: int) -> date:
    y, m = period_end.year, period_end.month + 1 + extra_months
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, day)


def _answer_text(reason: str, answer: dict[str, Any]) -> str:
    opts = {o["value"]: o["label"] for o in q.OPTIONS.get(reason, [])}
    label = str(opts.get(answer.get("choice", ""), answer.get("choice")))
    extra = [str(answer[k]) for k in ("purpose", "occasion", "participants", "invoice_no", "note") if answer.get(k)]
    return label + (f" ({'; '.join(extra)})" if extra else "")
