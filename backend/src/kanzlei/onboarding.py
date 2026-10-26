"""Onboarding an acquired firm: its clients, staff, master data and booking history from DATEV.

The firm package is a directory:

    firm.json                      firm, staff, clients (with assigned staff)
    clients/<id>/*.csv             DATEV EXTF files: Buchungsstapel (history), Debitoren/Kreditoren

History is imported as it was booked (locked: it is festgeschrieben in DATEV). Accounts the
standard chart excerpt does not know are listed for the group engineer to map to a family; the
report says how much of last year's volume the agent can already learn from.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from kanzlei.config import families
from kanzlei.db import Conn, event
from kanzlei.domain.chart import Account, Chart, chart
from kanzlei.domain.text import normalize_iban, normalize_name
from kanzlei.formats.extf import ExtfBooking, read_buchungsstapel, read_header, read_stammdaten
from kanzlei.formats.xml import FormatError
from kanzlei.storage import sha256


def _period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def upsert_firm(conn: Conn, data: dict[str, Any]) -> None:
    f = data["firm"]
    conn.execute(
        """INSERT INTO firms (id, name, city, chart, berater_nr, llm_agreement_on) VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, city = EXCLUDED.city, berater_nr = EXCLUDED.berater_nr,
           llm_agreement_on = EXCLUDED.llm_agreement_on""",
        (f["id"], f["name"], f.get("city", ""), f["chart"], f["berater_nr"], f.get("llm_agreement_on")),
    )
    for s in data.get("staff", []):
        conn.execute(
            """INSERT INTO staff (login, firm_id, name, role) VALUES (%s,%s,%s,%s)
               ON CONFLICT (login) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role, firm_id = EXCLUDED.firm_id""",
            (s["login"], f["id"] if s["role"] != "gruppe" else None, s["name"], s["role"]),
        )
    for c in data.get("clients", []):
        conn.execute(
            """INSERT INTO clients (id, firm_id, mandant_nr, name, legal_form, industry, booking_method, vat_regime, vat_period, dauerfrist,
               vat_id, own_ibans, contact_name, contact_email, fiscal_year_start_month)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, booking_method = EXCLUDED.booking_method, vat_regime = EXCLUDED.vat_regime,
               vat_period = EXCLUDED.vat_period, dauerfrist = EXCLUDED.dauerfrist, own_ibans = EXCLUDED.own_ibans,
               contact_name = EXCLUDED.contact_name, contact_email = EXCLUDED.contact_email""",
            (
                c["id"],
                f["id"],
                c["mandant_nr"],
                c["name"],
                c.get("legal_form", ""),
                c.get("industry", ""),
                c["booking_method"],
                c["vat_regime"],
                c.get("vat_period", "monat"),
                bool(c.get("dauerfrist", False)),
                c.get("vat_id"),
                [normalize_iban(i) for i in c.get("own_ibans", [])],
                c.get("contact_name", ""),
                c.get("contact_email", ""),
                int(c.get("fiscal_year_start_month", 1)),
            ),
        )
        for login in c.get("assigned", []):
            conn.execute(
                "INSERT INTO assignments (login, client_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (login, c["id"])
            )


def _family_side(b: ExtfBooking, ch: Chart, system: set[int]) -> int | None:
    """Which account of a history line says what it was for (not bank, not a personal account)."""
    for acct in (b.gegenkonto, b.konto):
        if acct not in system and not ch.is_personal(acct):
            return acct
    return None


def import_history(conn: Conn, firm_id: str, client_id: str, data: bytes, filename: str, actor: str) -> dict[str, Any]:
    digest = sha256(data)
    if conn.execute("SELECT 1 FROM imports WHERE firm_id = %s AND sha256 = %s", (firm_id, digest)).fetchone():
        return {"duplicate": True}
    chart_name = conn.execute("SELECT chart FROM firms WHERE id = %s", (firm_id,)).fetchone()["chart"]  # type: ignore[index]
    base = chart(chart_name)
    mapped = conn.execute(
        "SELECT account, name, family, role, tax FROM firm_accounts WHERE firm_id = %s AND family IS NOT NULL",
        (firm_id,),
    ).fetchall()
    ch = base.extend([Account(r["account"], r["name"], r["family"], r["tax"], False, r["role"]) for r in mapped])
    system = set(ch.system.values())
    header, rows = read_buchungsstapel(data)
    expected = "SKR" + header.chart if header.chart else chart_name
    if header.chart and expected != chart_name:
        raise FormatError(f"history is {expected}, the firm runs {chart_name}")
    unknown: Counter[int] = Counter()
    volume_known = volume_all = 0
    fams = families()
    for b in rows:
        side = _family_side(b, ch, system)
        fam_role = ch.family_of(side) if side is not None else None
        family, role = fam_role if fam_role else (None, None)
        if side is not None and fam_role is None:
            unknown[side] += 1
        tax_acct = side if side is not None else b.gegenkonto
        tax = ch.tax_of(tax_acct, b.bu) or "NONE"
        volume_all += b.amount_cents
        if family in fams or family in ("skonto_received", "skonto_granted"):
            volume_known += b.amount_cents
        conn.execute(
            """INSERT INTO bookings (client_id, period, booking_date, amount_cents, debit, credit, tax, text, doc_ref, family, role, origin, locked)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'import',true)""",
            (
                client_id,
                _period(b.belegdatum),
                b.belegdatum,
                b.amount_cents,
                b.debit,
                b.credit,
                tax,
                b.buchungstext,
                b.belegfeld1,
                family,
                role,
            ),
        )
    for acct, n in unknown.items():
        conn.execute(
            """INSERT INTO firm_accounts (firm_id, account, rows) VALUES (%s,%s,%s)
               ON CONFLICT (firm_id, account) DO UPDATE SET rows = firm_accounts.rows + EXCLUDED.rows""",
            (firm_id, acct, n),
        )
    summary = {
        "rows": len(rows),
        "from": header.date_from.isoformat() if header.date_from else None,
        "to": header.date_to.isoformat() if header.date_to else None,
        "unmapped_accounts": {str(k): v for k, v in unknown.most_common()},
        "volume_mapped_share": round(volume_known / volume_all, 4) if volume_all else 0.0,
    }
    conn.execute(
        "INSERT INTO imports (firm_id, client_id, kind, filename, sha256, rows, summary) VALUES (%s,%s,'buchungsstapel',%s,%s,%s,%s)",
        (firm_id, client_id, filename, digest, len(rows), Jsonb(summary)),
    )
    event(
        conn,
        actor,
        "onboarding.history",
        {"file": filename, "sha256": digest, **summary},
        firm=firm_id,
        client=client_id,
    )
    return summary


def import_master(conn: Conn, firm_id: str, client_id: str, data: bytes, filename: str, actor: str) -> dict[str, Any]:
    digest = sha256(data)
    if conn.execute("SELECT 1 FROM imports WHERE firm_id = %s AND sha256 = %s", (firm_id, digest)).fetchone():
        return {"duplicate": True}
    chart_name = conn.execute("SELECT chart FROM firms WHERE id = %s", (firm_id,)).fetchone()["chart"]  # type: ignore[index]
    ch = chart(chart_name)
    _, recs = read_stammdaten(data)
    n = 0
    for r in recs:
        kind = "kreditor" if ch.is_creditor(r.account) else ("debitor" if ch.is_debtor(r.account) else None)
        if kind is None:
            continue
        conn.execute(
            """INSERT INTO counterparties (client_id, kind, account, name, norm_name, iban, vat_id, country)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (client_id, account) DO UPDATE SET name = EXCLUDED.name,
               norm_name = EXCLUDED.norm_name, iban = EXCLUDED.iban, vat_id = EXCLUDED.vat_id, country = EXCLUDED.country""",
            (client_id, kind, r.account, r.name, normalize_name(r.name), normalize_iban(r.iban), r.vat_id, r.country),
        )
        n += 1
    conn.execute(
        "INSERT INTO imports (firm_id, client_id, kind, filename, sha256, rows, summary) VALUES (%s,%s,'stammdaten',%s,%s,%s,%s)",
        (firm_id, client_id, filename, digest, n, Jsonb({"records": n})),
    )
    event(conn, actor, "onboarding.master", {"file": filename, "records": n}, firm=firm_id, client=client_id)
    return {"records": n}


def import_package(conn: Conn, root: Path, actor: str = "onboarding") -> dict[str, Any]:
    """Imports a firm package (see module docstring). Idempotent: files already imported are skipped."""
    data = json.loads((root / "firm.json").read_text(encoding="utf-8"))
    upsert_firm(conn, data)
    firm_id = data["firm"]["id"]
    report: dict[str, Any] = {"firm": firm_id, "clients": {}}
    for c in data.get("clients", []):
        d = root / "clients" / c["id"]
        out: dict[str, Any] = {}
        if d.exists():
            files = sorted(d.glob("*.csv"))
            # Master data first, so history can be attributed to suppliers and customers.
            for f in sorted(files, key=lambda p: 0 if read_header(_first_line(p)).category == 16 else 1):
                raw = f.read_bytes()
                cat = read_header(_first_line(f)).category
                if cat == 16:
                    out.setdefault("master", []).append(import_master(conn, firm_id, c["id"], raw, f.name, actor))
                elif cat == 21:
                    out.setdefault("history", []).append(import_history(conn, firm_id, c["id"], raw, f.name, actor))
        report["clients"][c["id"]] = out
    return report


def _first_line(path: Path) -> list[str]:
    import csv
    import io

    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return next(csv.reader(io.StringIO(text.split("\n", 1)[0]), delimiter=";", quotechar='"'))
