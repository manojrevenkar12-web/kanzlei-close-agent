"""Closes the simulated months through the real engine, the way a firm works:

    statement and receipts in -> close run -> client answers in the portal -> answers applied
    -> staff review (accept, correct, or book by hand) -> unanswered items parked
    -> tax advisor signs off -> DATEV export

The simulated client answers from what it knows (scenario `says`); the simulated accountant
always knows the truth, so every review ends correct, and what is measured is how much of the
month needed a person and how often the agent was wrong when it booked alone.
"""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from kanzlei.db import Pool, as_system, as_user, principal
from kanzlei.domain.models import Line, Proposal
from kanzlei.engine.close import Engine
from kanzlei.onboarding import import_package
from kanzlei_sim import render
from kanzlei_sim.scenario import Client, Event, Firm, HistorySpec, cents
from kanzlei_sim.truth import TLine, event_lines, system


@dataclass
class Record:
    set: str
    firm: str
    client: str
    period: str
    event: str
    kind: str
    truth_family: str
    family: str | None
    first_route: str
    first_correct: bool
    confidence: float
    features: list[float]
    flags: list[str]
    questions: list[str] = field(default_factory=list)
    question_needed: list[bool] = field(default_factory=list)
    path: str = ""  # auto | client | accepted | corrected | manual | parked
    final_correct: bool | None = None
    source: str = ""


# --- preparing a scenario ---------------------------------------------------------------------------


def assign_accounts(firm: Firm) -> None:
    """Kreditor/Debitor numbers for OPOS clients' invoice partners (as the firm's DATEV has them)."""
    for c in firm.clients:
        if c.booking_method != "opos":
            continue
        used = {p.account for p in c.parties if p.account}
        nxt = {
            "supplier": max([a for a in used if a and a >= 70000] + [70000]) + 1,
            "customer": max([a for a in used if a and a < 70000] + [10000]) + 1,
        }
        partners = sorted({e.party for evs in c.months.values() for e in evs if e.kind == "invoice"})
        for key in partners:
            p = c.party(key)
            if p.account:
                continue
            role = "customer" if p.role == "customer" else "supplier"
            p.account = nxt[role]
            nxt[role] += 1


def personal_map(c: Client) -> dict[str, int]:
    return {p.key: p.account for p in c.parties if p.account}


def invoices_index(c: Client) -> dict[str, Event]:
    return {e.id: e for evs in c.months.values() for e in evs if e.kind == "invoice"}


def history_rows(firm: Firm, c: Client, periods: list[str]) -> list[tuple[date, TLine, str, str]]:
    """The firm's past bookings: simulated months, or HistorySpec lines of a hand-written scenario."""
    pm, inv = personal_map(c), invoices_index(c)
    rows: list[tuple[date, TLine, str, str]] = []
    for period in periods:
        for e in c.months.get(period, []):
            if e.truth is None:
                continue
            on = e.on or (e.document.issue_date if e.document else None) or date(int(period[:4]), int(period[5:7]), 1)
            p = c.party(e.party)
            for ln in event_lines(e, c, firm, pm, inv):
                rows.append((on, ln, p.name, ln.ref or (e.document.number if e.document else "")))
    for h in c.history:
        rows += spec_rows(firm, c, h)
    return rows


def spec_rows(firm: Firm, c: Client, h: HistorySpec) -> list[tuple[date, TLine, str, str]]:
    from kanzlei_sim.ids import seeded
    from kanzlei_sim.scenario import Truth

    p = c.party(h.party)
    rng = seeded("hist", c.id, h.party, h.family)
    out = []
    first = min(c.months) if c.months else "2026-07"
    end_y, end_m = int(first[:4]), int(first[5:7]) - 1  # history ends the month before the scenario
    if end_m == 0:
        end_y, end_m = end_y - 1, 12
    for k in range(h.months):
        y, m = end_y, end_m - k
        while m <= 0:
            y, m = y - 1, m + 12
        for j in range(h.per_month):
            amt = h.amount * (1 + rng.uniform(-h.vary, h.vary)) if h.vary else h.amount
            ev = Event(
                id=f"h-{h.party}-{k}-{j}",
                kind="payment",
                party=h.party,
                amount=round(amt, 2),
                on=date(y, m, min(28, 3 + 5 * j + k % 5)),
                truth=Truth(family=h.family, tax=h.tax),
            )
            for ln in event_lines(ev, c, firm, {}, {}):
                out.append((ev.on or date(y, m, 1), ln, h.text or p.name, ""))
    return out


def build_package(firm: Firm, root: Path, history_periods: list[str]) -> None:
    assign_accounts(firm)
    hist, master = {}, {}
    for c in firm.clients:
        rows = history_rows(firm, c, history_periods)
        if rows:
            lo, hi = min(r[0] for r in rows), max(r[0] for r in rows)
            hist[c.id] = render.extf_history(firm, c, sorted(rows, key=lambda r: r[0]), date(lo.year, lo.month, 1), hi)
        if c.booking_method == "opos" and any(p.account for p in c.parties):
            master[c.id] = render.extf_master(firm, c)
    render.write_package(firm, root, hist, master)


def seed(pool: Pool, firms: list[Firm], root: Path, history_periods: list[str]) -> dict[str, Any]:
    out = {}
    for f in firms:
        d = root / f.id
        build_package(f, d, history_periods)
        with as_system(pool) as conn:
            out[f.id] = import_package(conn, d, actor="sim")
    return out


# --- the simulated client and accountant ------------------------------------------------------------


def corrected(doc: Any) -> Any:
    d = copy.deepcopy(doc)
    d.missing = []
    d.arrives = "with_statement"
    return d


def client_answer(e: Event, reason: str) -> tuple[dict[str, Any] | None, Any]:
    """(answer, document spec to upload) for a question about event `e`."""
    if not e.answers:
        return None, None
    said = e.says.get(reason)
    fam = e.truth.family if e.truth else ""
    if said:
        a = dict(said)
        if a.get("choice") == "upload":
            doc = corrected(e.document) if reason == "invoice_incomplete" else e.document
            return a, doc
        return a, None
    # Not prepared for this question: answer from what the client knows.
    if fam == "private_withdrawal":
        return {"choice": "private"}, None
    if reason == "missing_receipt":
        if e.document is not None and e.document.arrives != "never":
            return {"choice": "upload"}, e.document
        return {"choice": "no_receipt", "purpose": "Betriebsausgabe"}, None
    if reason == "private_or_business":
        return {"choice": "business", "purpose": "Betriebsausgabe"}, None
    if reason == "meals_details":
        return {"choice": "details", "occasion": "Geschäftsessen", "participants": "Geschäftspartner"}, None
    if reason == "unknown_credit":
        if fam == "revenue" and e.document is not None:
            return {"choice": "customer", "invoice_no": e.document.number}, e.document
        if fam == "private_deposit":
            return {"choice": "private_deposit"}, None
        return {"choice": "other", "note": "Erstattung"}, None
    if reason == "invoice_incomplete":
        return {"choice": "not_available"}, None
    return None, None


def needed(e: Event, reason: str) -> bool:
    """Did the agent need the client for this? (the information was not in the files)"""
    fam = e.truth.family if e.truth else ""
    if reason in e.says and (
        reason != "missing_receipt"
        or (e.document and e.document.arrives != "with_statement")
        or fam == "private_withdrawal"
    ):
        return True
    if reason == "missing_receipt":
        return e.document is None or e.document.arrives != "with_statement" or fam == "private_withdrawal"
    if reason == "private_or_business":
        return fam == "private_withdrawal"
    if reason == "meals_details":
        return fam in ("meals", "private_withdrawal") and not any(
            "Anlass" in n for n in (e.document.notes if e.document else [])
        )
    if reason == "invoice_incomplete":
        return bool(e.document and e.document.missing)
    return reason == "unknown_credit" and (e.document is None or e.document.arrives != "with_statement")


def norm(lines: list[Line] | list[TLine]) -> list[tuple[int, int, str, int]]:
    """Lines as (debit, credit, tax, amount), amounts on the same accounts and tax code summed
    (splitting one booking line into two on the same accounts changes nothing)."""
    acc: dict[tuple[int, int, str], int] = defaultdict(int)
    for ln in lines:
        if isinstance(ln, Line):
            acc[(ln.debit, ln.credit, ln.tax)] += ln.amount_cents
        else:
            acc[(ln.debit, ln.credit, ln.tax)] += ln.amount
    return sorted((d, c, t, a) for (d, c, t), a in acc.items())


def to_lines(tl: list[TLine], on: date, text: str) -> list[Line]:
    return [Line(on, t.amount, t.debit, t.credit, t.tax, text[:60], None, None, t.ref) for t in tl]


# --- closing a month ----------------------------------------------------------------------------------


@dataclass
class MonthResult:
    records: list[Record]
    ustva_engine: dict[str, Any]
    ustva_truth: dict[str, dict[str, int]]
    signed: bool
    closing_cents: int
    error: str | None = None


def close_month(
    engine: Engine, pool: Pool, firm: Firm, c: Client, period: str, opening: int, set_name: str
) -> MonthResult:
    events = c.months.get(period, [])
    accountant = principal(pool, c.assigned[0])
    berater = principal(pool, next(s["login"] for s in firm.staff if s["role"] == "berater"))
    assert accountant and berater
    camt, closing = render.camt053(c, period, events, opening)
    pays = [e for e in events if e.kind == "payment"]
    pm, invs = personal_map(c), invoices_index(c)
    truth = {e.id: event_lines(e, c, firm, pm, invs) for e in events if e.truth}
    doc_event: dict[int, str] = {}

    def upload(conn: Any, e: Event, spec: Any, source: str) -> int:
        name, data = render.document(c, c.party(e.party), spec)
        r = engine.import_document(conn, c.id, data, name, source=source, direction=spec.direction, actor=accountant)
        doc_event[r["id"]] = e.id
        return int(r["id"])

    with as_user(pool, accountant) as conn:
        engine.import_statement(conn, c.id, camt, f"camt053_{c.mandant_nr}_{period}.xml", accountant)
        for e in events:
            if e.document and e.document.arrives == "with_statement":
                upload(conn, e, e.document, "upload")
        engine.run(conn, c.id, period, accountant)
        tx_rows = conn.execute(
            "SELECT t.id, t.seq FROM transactions t JOIN statements s ON s.id = t.statement_id WHERE t.client_id = %s AND t.period = %s ORDER BY t.seq",
            (c.id, period),
        ).fetchall()
    tx_event = {r["id"]: pays[r["seq"] - 1].id for r in tx_rows}
    ev_by_id = {e.id: e for e in events}

    def event_of(item: dict[str, Any]) -> str | None:
        if item["transaction_id"]:
            return tx_event.get(item["transaction_id"])
        for d in item["document_ids"]:
            if d in doc_event:
                return doc_event[d]
        return None

    records: dict[int, Record] = {}

    def snapshot() -> None:
        with as_user(pool, accountant) as conn:
            for it in conn.execute(
                "SELECT * FROM items WHERE client_id = %s AND period = %s", (c.id, period)
            ).fetchall():
                if it["id"] in records:
                    continue
                eid = event_of(it)
                if eid is None or eid not in truth:
                    continue
                e = ev_by_id[eid]
                if it["kind"] == "invoice" and e.kind != "invoice":
                    continue  # a receipt the agent wanted to book on receipt; counted with its payment
                p = Proposal.from_json(it["proposal"])
                records[it["id"]] = Record(
                    set_name,
                    firm.id,
                    c.id,
                    period,
                    eid,
                    it["kind"],
                    e.truth.family if e.truth else "",
                    p.family,
                    p.route,
                    norm(p.lines) == norm(truth[eid]),
                    p.confidence,
                    p.features,
                    p.flags,
                    source=p.source,
                )

    snapshot()
    asked: dict[int, list[str]] = defaultdict(list)
    for _round in range(2):
        with as_system(pool) as conn:
            open_q = conn.execute(
                """SELECT qi.item_id, qi.reason, q.id AS qid FROM query_items qi JOIN queries q ON q.id = qi.query_id
                   WHERE q.client_id = %s AND q.period = %s AND q.status = 'offen' AND qi.answer IS NULL""",
                (c.id, period),
            ).fetchall()
            items = {
                r["id"]: dict(r)
                for r in conn.execute(
                    "SELECT * FROM items WHERE client_id = %s AND period = %s", (c.id, period)
                ).fetchall()
            }
        if not open_q:
            break
        for q in open_q:
            it = items[q["item_id"]]
            eid = event_of(it)
            if eid is None:
                continue
            e = ev_by_id[eid]
            asked[q["item_id"]].append(q["reason"])
            ans, doc = client_answer(e, q["reason"])
            if ans is None:
                continue
            with as_system(pool) as conn:
                if doc is not None:
                    ans["document_id"] = upload(conn, e, doc, "portal")
                token_hash = conn.execute("SELECT token_hash FROM queries WHERE id = %s", (q["qid"],)).fetchone()[
                    "token_hash"
                ]  # type: ignore[index]
                conn.execute("SELECT portal_answer(%s, %s, %s)", (token_hash, q["item_id"], Jsonb(ans)))
        with as_user(pool, accountant) as conn:
            engine.apply_answers(conn, c.id, period, accountant)
            engine.run(conn, c.id, period, accountant)
        snapshot()

    # Staff review: accept what is right; otherwise correct the family (and tax); otherwise book by hand.
    with as_user(pool, accountant) as conn:
        for it in conn.execute(
            "SELECT * FROM items WHERE client_id = %s AND period = %s AND state = 'review' ORDER BY id", (c.id, period)
        ).fetchall():
            eid = event_of(it)
            if eid is None or eid not in truth:
                if it["kind"] == "payment":
                    engine.park(conn, it["id"], accountant, "nicht zuordenbar")
                continue
            want = truth[eid]
            if it["kind"] == "invoice" and ev_by_id[eid].kind != "invoice":
                engine.dismiss(conn, it["id"], accountant, "wird mit der Zahlung gebucht")
                continue
            p = Proposal.from_json(it["proposal"])
            if norm(p.lines) == norm(want):
                engine.accept(conn, it["id"], accountant)
                continue
            e = ev_by_id[eid]
            fam = e.truth.family if e.truth else ""
            done = False
            if fam not in ("clearing",):
                try:
                    with conn.transaction():
                        q = engine.correct(
                            conn, it["id"], accountant, family=fam, tax=_single_tax(want), reason="Simulation"
                        )
                        if norm(q.lines) != norm(want):
                            raise _Undo()
                    done = True
                except Exception:
                    done = False
            if not done:
                on = (
                    conn.execute(
                        "SELECT booking_date FROM transactions WHERE id = %s", (it["transaction_id"],)
                    ).fetchone()
                    if it["transaction_id"]
                    else None
                )
                engine.book_manual(
                    conn,
                    it["id"],
                    accountant,
                    to_lines(
                        want,
                        on["booking_date"] if on else date(int(period[:4]), int(period[5:7]), 1),
                        c.party(e.party).name,
                    ),
                    "Simulation",
                )
        for it in conn.execute(
            "SELECT id, kind FROM items WHERE client_id = %s AND period = %s AND state = 'client'", (c.id, period)
        ).fetchall():
            if it["kind"] == "payment":
                engine.park(conn, it["id"], accountant, "Mandant hat nicht geantwortet")
            else:
                conn.execute("UPDATE items SET state = 'parked', decision = 'parked' WHERE id = %s", (it["id"],))
        final = {
            r["id"]: dict(r)
            for r in conn.execute("SELECT * FROM items WHERE client_id = %s AND period = %s", (c.id, period)).fetchall()
        }
        ust = engine.ustva(conn, c.id, period)
    signed, err = True, None
    with as_user(pool, berater) as conn:
        try:
            with conn.transaction():
                engine.sign_off(conn, c.id, period, berater, acknowledge_flags=True)
        except Exception as ex:  # recorded; the month stays open
            signed, err = False, str(ex)
    for item_id, rec in records.items():
        it = final[item_id]
        rec.path = {
            "auto": "auto",
            "client": "client",
            "accepted": "accepted",
            "corrected": "corrected",
            "parked": "parked",
        }.get(it["decision"] or "", it["decision"] or "open")
        if rec.path == "corrected" and it["final"] and any(ln.get("family") is None for ln in it["final"]["lines"]):
            rec.path = "manual"
        rec.questions = asked.get(item_id, [])
        rec.question_needed = [needed(ev_by_id[rec.event], r) for r in rec.questions]
        if it["final"] and it["decision"] != "parked":
            rec.final_correct = norm([Line.from_json(x) for x in it["final"]["lines"]]) == norm(truth[rec.event])
    ust_truth = truth_ustva(c, firm, records, final)
    return MonthResult(list(records.values()), ust, ust_truth, signed, closing, err)


class _Undo(Exception):
    pass


def _single_tax(lines: list[TLine]) -> str | None:
    taxes = {ln.tax for ln in lines}
    return taxes.pop() if len(taxes) == 1 else None


def truth_ustva(
    c: Client, firm: Firm, records: dict[int, Record], final: dict[int, dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """The VAT return the truth implies, for the items that were booked (parked ones excluded),
    computed here without the engine's code."""
    import yaml

    from kanzlei_sim.truth import CONFIG

    cfg = yaml.safe_load((CONFIG / "tax.yaml").read_text(encoding="utf-8"))
    parked = {r.event for i, r in records.items() if final[i]["decision"] == "parked"}
    ch = firm.chart
    sysacc = {system(ch, k) for k in ("bank", "cash", "transit", "receivables", "payables", "suspense")}

    def is_tax(a: int) -> bool:
        return a not in sysacc and not (10000 <= a <= 99999)

    from decimal import ROUND_HALF_UP, Decimal

    def hu(x: Decimal) -> int:
        return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    keep_events = {r.event for r in records.values() if r.event not in parked}
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"base_cents": 0, "tax_cents": 0})
    period = next(iter(records.values())).period if records else ""
    for ev in c.months.get(period, []):
        if ev.id not in keep_events or ev.truth is None:
            continue
        for ln in event_lines(ev, c, firm, personal_map(c), invoices_index(c)):
            spec = cfg["kennzahlen"].get(ln.tax)
            if not spec:
                continue
            d, cr = is_tax(ln.debit), is_tax(ln.credit)
            on_debit = d if d != cr else True
            output = ln.tax in ("U19", "U7", "IGL", "EU_SVC", "RC_OUT", "FREI")
            sign = (-1 if on_debit else 1) if output else (1 if on_debit else -1)
            rate = int(spec.get("rate", cfg["rates"].get(ln.tax, 0)))
            if ln.tax in ("U19", "U7", "V19", "V7"):
                tax = hu(Decimal(ln.amount) * rate / (100 + rate))
                net = ln.amount - tax
            else:
                net, tax = ln.amount, (hu(Decimal(ln.amount) * rate / 100) if rate else 0)
            if "base" in spec:
                out[spec["base"]]["base_cents"] += sign * net
                if ln.tax in ("U19", "U7", "IGE19"):
                    out[spec["base"]]["tax_cents"] += sign * tax
            if "tax" in spec and spec["tax"] != spec.get("base"):
                out[spec["tax"]]["tax_cents"] += sign * tax
            if "input" in spec:
                out[spec["input"]]["tax_cents"] += sign * tax
    owed = sum(out[k]["tax_cents"] for k in ("81", "86", "47", "85", "89") if k in out)
    ded = sum(out[k]["tax_cents"] for k in ("66", "61", "67") if k in out)
    out["83"]["tax_cents"] = owed - ded
    return {k: dict(v) for k, v in out.items()}


def opening_for(c: Client, period: str) -> int:
    bal = c.opening_cents
    for p in sorted(c.months):
        if p >= period:
            break
        bal += sum(cents(e.amount) for e in c.months[p] if e.kind == "payment")
    return bal


def run_months(engine: Engine, pool: Pool, firms: list[Firm], periods: list[str], set_name: str) -> list[MonthResult]:
    results = []
    for p in periods:
        for f in firms:
            for c in f.clients:
                if p not in c.months:
                    continue
                results.append(close_month(engine, pool, f, c, p, opening_for(c, p), set_name))
    return results


def records_json(results: list[MonthResult]) -> list[dict[str, Any]]:
    return [asdict(r) for m in results for r in m.records]


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]
