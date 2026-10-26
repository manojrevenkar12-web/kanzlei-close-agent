"""HTTP API. Staff endpoints run inside the person's database rights (row-level security); the
client portal reaches its own questions through a token only; the group view gets aggregates."""

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from kanzlei.api.auth import issue, verify
from kanzlei.config import Settings, families, settings, tax_config
from kanzlei.db import SYSTEM, Conn, Pool, Principal, as_system, as_user, create_pool, event, principal
from kanzlei.domain.chart import Chart
from kanzlei.domain.models import CLIENT_FLAGS, REVIEW_FLAGS
from kanzlei.domain.money import fmt_de
from kanzlei.engine.classifier import Classifier
from kanzlei.engine.close import CloseError, Engine, _due_date, period_bounds
from kanzlei.engine.decision import DecisionModel
from kanzlei.engine.llm import ModelReader
from kanzlei.engine.queries import valid_answer
from kanzlei.formats.invoice import Invoice
from kanzlei.storage import Store, sha256, store_from_url

REQUESTS = Counter("kanzlei_requests_total", "HTTP requests", ["route", "status"])
LATENCY = Histogram("kanzlei_request_seconds", "HTTP latency", ["route"])
DECISIONS = Counter("kanzlei_item_decisions_total", "Staff decisions on items", ["decision"])
MAX_UPLOAD = 15 * 1024 * 1024


@dataclass
class Deps:
    pool: Pool
    settings: Settings
    engine: Engine
    store: Store


class SessionIn(BaseModel):
    login: str


class CorrectIn(BaseModel):
    family: str
    tax: str | None = None
    reason: str = Field(default="", max_length=300)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=300)


class SignOffIn(BaseModel):
    acknowledge_flags: bool = False


class AnswerIn(BaseModel):
    choice: str
    purpose: str | None = Field(default=None, max_length=300)
    occasion: str | None = Field(default=None, max_length=300)
    participants: str | None = Field(default=None, max_length=300)
    invoice_no: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=300)


class MapAccountIn(BaseModel):
    family: str
    role: str | None = None
    tax: str = "*"


def _period(p: str) -> str:
    try:
        y, m = int(p[:4]), int(p[5:7])
        if len(p) != 7 or p[4] != "-" or not 1 <= m <= 12 or y < 2000:
            raise ValueError
    except ValueError as e:
        raise HTTPException(400, "Zeitraum als JJJJ-MM angeben") from e
    return p


def build_app(deps: Deps) -> FastAPI:
    app = FastAPI(title="kanzlei-close-agent", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[deps.settings.cors_origin],
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def measure(request: Request, call_next: Any) -> Any:
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        LATENCY.labels(path).observe(time.perf_counter() - start)
        REQUESTS.labels(path, str(response.status_code)).inc()
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(CloseError)
    async def close_error(_: Request, exc: CloseError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def current(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bitte anmelden")
        login = verify(authorization[7:], deps.settings.token_secret)
        if login is None:
            raise HTTPException(401, "Sitzung abgelaufen")
        p = principal(deps.pool, login)
        if p is None:
            raise HTTPException(401, "Unbekannte Person")
        return p

    Me = Annotated[Principal, Depends(current)]

    def conn_for(p: Principal) -> Iterator[Conn]:
        with as_user(deps.pool, p) as conn:
            yield conn

    def staff_conn(p: Me) -> Iterator[Conn]:
        if p.group:
            raise HTTPException(403, "Die Gruppe sieht keine Mandantendaten")
        yield from conn_for(p)

    Db = Annotated[Conn, Depends(staff_conn)]

    def visible_client(conn: Conn, client_id: str) -> dict[str, Any]:
        r = conn.execute("SELECT * FROM clients WHERE id = %s", (client_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "Mandant nicht gefunden")
        return dict(r)

    def chart_of(conn: Conn, client_id: str) -> Chart:
        prof = deps.engine.profile(conn, client_id)
        return deps.engine.chart_for(conn, prof.firm_id, prof.chart)

    # --- health, metrics, session ---------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with as_system(deps.pool) as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/api/metrics")
    def metrics(authorization: Annotated[str | None, Header()] = None) -> Response:
        token = deps.settings.metrics_token
        if not token or authorization != f"Bearer {token}":
            raise HTTPException(401)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/demo-users")
    def demo_users() -> list[dict[str, Any]]:
        if not deps.settings.demo_mode:
            raise HTTPException(404)
        with as_system(deps.pool) as conn:
            rows = conn.execute(
                """SELECT s.login, s.name, s.role, f.name AS firm FROM staff s LEFT JOIN firms f ON f.id = s.firm_id
                   ORDER BY s.firm_id NULLS LAST, s.role DESC, s.name"""
            ).fetchall()
        return [dict(r) for r in rows]

    @app.post("/api/session")
    def session(body: SessionIn) -> dict[str, Any]:
        if not deps.settings.demo_mode:
            raise HTTPException(404, "Anmeldung über den Identity Provider der Gruppe")
        p = principal(deps.pool, body.login)
        if p is None:
            raise HTTPException(404, "Unbekannte Person")
        return {"token": issue(p.login, deps.settings.token_secret)}

    @app.get("/api/me")
    def me(p: Me) -> dict[str, Any]:
        firm = None
        if p.firm_id:
            with as_user(deps.pool, p) as conn:
                r = conn.execute("SELECT id, name, city, chart FROM firms WHERE id = %s", (p.firm_id,)).fetchone()
                firm = dict(r) if r else None
        return {"login": p.login, "name": p.name, "role": p.role, "firm": firm, "can_sign_off": p.can_sign_off}

    @app.get("/api/families")
    def list_families(_: Me) -> list[dict[str, Any]]:
        return [{"code": f.code, "label": f.label, "side": f.side} for f in families().values()]

    # --- the close board --------------------------------------------------------------------------

    @app.get("/api/periods")
    def periods(conn: Db) -> list[str]:
        rows = conn.execute(
            "SELECT DISTINCT period FROM transactions UNION SELECT period FROM closes ORDER BY 1 DESC"
        ).fetchall()
        return [r["period"] for r in rows]

    @app.get("/api/closes")
    def board(conn: Db, period: Annotated[str, Query()]) -> list[dict[str, Any]]:
        period = _period(period)
        rows = conn.execute(
            """SELECT c.id, c.name, c.mandant_nr, c.legal_form, c.industry, c.booking_method, c.vat_regime, c.vat_period, c.dauerfrist,
                      cl.status, cl.last_run_at, cl.signed_at, cl.signed_by,
                      count(i.id) AS items,
                      count(i.id) FILTER (WHERE i.decision = 'auto') AS auto,
                      count(i.id) FILTER (WHERE i.decision IN ('accepted', 'corrected')) AS reviewed,
                      count(i.id) FILTER (WHERE i.decision = 'client') AS by_client,
                      count(i.id) FILTER (WHERE i.state = 'review') AS open_review,
                      count(i.id) FILTER (WHERE i.state = 'client') AS open_client,
                      count(i.id) FILTER (WHERE i.state = 'parked') AS parked,
                      (SELECT count(*) FROM transactions t WHERE t.client_id = c.id AND t.period = %s) AS transactions,
                      (SELECT count(*) FROM transactions t WHERE t.client_id = c.id AND t.period = %s
                         AND NOT EXISTS (SELECT 1 FROM items x WHERE x.transaction_id = t.id)) AS unprocessed,
                      (SELECT string_agg(s.name, ', ' ORDER BY s.name) FROM assignments a JOIN staff s ON s.login = a.login WHERE a.client_id = c.id) AS assigned
               FROM clients c
               LEFT JOIN closes cl ON cl.client_id = c.id AND cl.period = %s
               LEFT JOIN items i ON i.client_id = c.id AND i.period = %s
               GROUP BY c.id, cl.status, cl.last_run_at, cl.signed_at, cl.signed_by
               ORDER BY c.name""",
            (period, period, period, period),
        ).fetchall()
        _, end = period_bounds(period)
        cfg = tax_config()
        out = []
        for r in rows:
            d = dict(r)
            d["status"] = d["status"] or "offen"
            d["due_on"] = _due_date(end, cfg.due_day, cfg.dauerfrist_extra_months if d["dauerfrist"] else 0).isoformat()
            quarterly = d["vat_period"] == "quartal"
            d["files_vat_this_month"] = (not quarterly) or end.month in (3, 6, 9, 12)
            out.append(d)
        return out

    # --- import ---------------------------------------------------------------------------------------

    async def _read(upload: UploadFile) -> bytes:
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Datei zu groß (max. 15 MB)")
        return data

    @app.post("/api/clients/{client_id}/statements")
    async def upload_statement(client_id: str, p: Me, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        data = await _read(file)
        with as_user(deps.pool, p) as conn:
            visible_client(conn, client_id)
            return deps.engine.import_statement(conn, client_id, data, file.filename or "camt053.xml", p)

    @app.post("/api/clients/{client_id}/documents")
    async def upload_document(
        client_id: str, p: Me, file: Annotated[UploadFile, File()], direction: Annotated[str, Form()] = "in"
    ) -> dict[str, Any]:
        if direction not in ("in", "out"):
            raise HTTPException(400, "direction: in oder out")
        data = await _read(file)
        with as_user(deps.pool, p) as conn:
            visible_client(conn, client_id)
            prof = deps.engine.profile(conn, client_id)
            reader = deps.engine.reader_for(prof) if deps.engine.reader_for and prof.llm_allowed else None
            return deps.engine.import_document(
                conn,
                client_id,
                data,
                file.filename or "beleg",
                source="upload",
                direction=direction,
                actor=p,
                reader=reader,
            )

    # --- running the close ----------------------------------------------------------------------------

    @app.post("/api/clients/{client_id}/periods/{period}/run")
    def run(client_id: str, period: str, p: Me, conn: Db) -> dict[str, Any]:
        visible_client(conn, client_id)
        summary = deps.engine.run(conn, client_id, _period(period), p)
        q = summary.pop("query", None)
        if q:
            summary["query"] = {"id": q["id"], "items": q["items"], "portal_link": f"/portal/{q['token']}"}
        return summary

    @app.post("/api/clients/{client_id}/periods/{period}/apply-answers")
    def apply_answers(client_id: str, period: str, p: Me, conn: Db) -> dict[str, Any]:
        visible_client(conn, client_id)
        return {"applied": deps.engine.apply_answers(conn, client_id, _period(period), p)}

    def _item_rows(conn: Conn, where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in conn.execute(
                f"""SELECT i.*, t.booking_date, t.amount_cents AS tx_amount, t.counterparty_name, t.counterparty_iban, t.remittance
                    FROM items i LEFT JOIN transactions t ON t.id = i.transaction_id WHERE {where}
                    ORDER BY CASE i.state WHEN 'client' THEN 0 WHEN 'review' THEN 1 WHEN 'parked' THEN 2 ELSE 3 END, t.booking_date NULLS LAST, i.id""",
                params,
            ).fetchall()
        ]

    def _lines_view(lines: list[dict[str, Any]], ch: Chart) -> list[dict[str, Any]]:
        out = []
        for ln in lines:
            out.append(
                {
                    **ln,
                    "debit_label": ch.fmt(ln["debit"]) + " " + ch.name_of(ln["debit"]),
                    "credit_label": ch.fmt(ln["credit"]) + " " + ch.name_of(ln["credit"]),
                    "bu": ch.bu_key(
                        ln["debit"]
                        if not ch.is_personal(ln["debit"]) and ln["debit"] not in ch.system.values()
                        else ln["credit"],
                        ln["tax"],
                    ),
                }
            )
        return out

    def _summary(r: dict[str, Any], ch: Chart) -> dict[str, Any]:
        prop = r["proposal"]
        fams = families()
        flags = prop.get("flags", [])
        lines = (r["final"] or prop).get("lines", [])
        amount = (
            r["tx_amount"] if r["tx_amount"] is not None else -sum(ln["amount_cents"] for ln in prop.get("lines", []))
        )
        return {
            "id": r["id"],
            "kind": r["kind"],
            "state": r["state"],
            "decision": r["decision"],
            "date": (r["booking_date"] or (date.fromisoformat(lines[0]["date"]) if lines else None)),
            "amount_cents": amount,
            "counterparty": r["counterparty_name"] or (prop.get("counterparty") or {}).get("name", ""),
            "remittance": r["remittance"] or "",
            "family": prop.get("family"),
            "family_label": fams[prop["family"]].label
            if prop.get("family") in fams
            else ("Ausgleich offener Posten" if prop.get("family") == "clearing" else None),
            "tax": prop.get("tax"),
            "confidence": prop.get("confidence", 0.0),
            "source": prop.get("source"),
            "flags": [
                {"code": f, "label": CLIENT_FLAGS.get(f) or REVIEW_FLAGS.get(f, f), "client": f in CLIENT_FLAGS}
                for f in flags
            ],
            "documents": len(r["document_ids"]),
            "accounts": [ch.fmt(ln["debit"] if ln["credit"] == ch.system["bank"] else ln["credit"]) for ln in lines][
                :3
            ],
        }

    @app.get("/api/clients/{client_id}/periods/{period}/items")
    def items(client_id: str, period: str, conn: Db, state: str | None = None) -> dict[str, Any]:
        period = _period(period)
        client = visible_client(conn, client_id)
        ch = chart_of(conn, client_id)
        where = "i.client_id = %s AND i.period = %s" + (" AND i.state = %s" if state else "")
        params: tuple[Any, ...] = (client_id, period, state) if state else (client_id, period)
        rows = _item_rows(conn, where, params)
        close = conn.execute(
            "SELECT * FROM closes WHERE client_id = %s AND period = %s", (client_id, period)
        ).fetchone()
        return {
            "client": {
                k: client[k]
                for k in (
                    "id",
                    "name",
                    "mandant_nr",
                    "booking_method",
                    "vat_regime",
                    "vat_period",
                    "legal_form",
                    "industry",
                )
            },
            "chart": ch.name,
            "status": close["status"] if close else "offen",
            "run_summary": close["run_summary"] if close else None,
            "items": [_summary(r, ch) for r in rows],
        }

    @app.get("/api/items/{item_id}")
    def item(item_id: int, conn: Db) -> dict[str, Any]:
        rows = _item_rows(conn, "i.id = %s", (item_id,))
        if not rows:
            raise HTTPException(404, "Posten nicht gefunden")
        r = rows[0]
        ch = chart_of(conn, r["client_id"])
        docs = conn.execute(
            "SELECT id, filename, format, direction, source, invoice, received_at FROM documents WHERE id = ANY(%s) ORDER BY id",
            (list(r["document_ids"]),),
        ).fetchall()
        prop = r["proposal"]
        questions = conn.execute(
            """SELECT qi.reason, qi.question, qi.answer, qi.answered_at, q.status, q.sent_at FROM query_items qi JOIN queries q ON q.id = qi.query_id
               WHERE qi.item_id = %s ORDER BY qi.id""",
            (item_id,),
        ).fetchall()
        cp = prop.get("counterparty") or {}
        history = []
        if cp.get("name"):
            history = [
                dict(h)
                for h in conn.execute(
                    """SELECT b.booking_date, b.amount_cents, b.debit, b.credit, b.tax, b.family FROM bookings b
                       WHERE b.client_id = %s AND (b.text = %s) AND b.family IS NOT NULL ORDER BY b.booking_date DESC LIMIT 6""",
                    (r["client_id"], cp["name"][:60]),
                ).fetchall()
            ]
        return {
            **_summary(r, ch),
            "client_id": r["client_id"],
            "period": r["period"],
            "chart": ch.name,
            "iban": r["counterparty_iban"],
            "proposal_lines": _lines_view(prop.get("lines", []), ch),
            "final_lines": _lines_view((r["final"] or {}).get("lines", []), ch) if r["final"] else None,
            "reasons": prop.get("reasons", []),
            "documents": [
                {
                    "id": d["id"],
                    "filename": d["filename"],
                    "format": d["format"],
                    "direction": d["direction"],
                    "source": d["source"],
                    "invoice": _invoice_view(d["invoice"]),
                }
                for d in docs
            ],
            "questions": [dict(q) for q in questions],
            "history": [
                {**h, "account": ch.fmt(h["debit"] if h["credit"] == ch.system["bank"] else h["credit"])}
                for h in history
            ],
            "decided_by": r["decided_by"],
            "decided_at": r["decided_at"],
        }

    def _decide(item_id: int, p: Principal, conn: Conn, decision: str, fn: Any) -> dict[str, Any]:
        fn()
        DECISIONS.labels(decision).inc()
        return item(item_id, conn)

    @app.post("/api/items/{item_id}/accept")
    def accept(item_id: int, p: Me, conn: Db) -> dict[str, Any]:
        return _decide(item_id, p, conn, "accepted", lambda: deps.engine.accept(conn, item_id, p))

    @app.post("/api/items/{item_id}/correct")
    def correct(item_id: int, body: CorrectIn, p: Me, conn: Db) -> dict[str, Any]:
        return _decide(
            item_id,
            p,
            conn,
            "corrected",
            lambda: deps.engine.correct(conn, item_id, p, family=body.family, tax=body.tax, reason=body.reason),
        )

    @app.post("/api/items/{item_id}/park")
    def park(item_id: int, body: NoteIn, p: Me, conn: Db) -> dict[str, Any]:
        return _decide(item_id, p, conn, "parked", lambda: deps.engine.park(conn, item_id, p, body.note))

    @app.post("/api/items/{item_id}/dismiss")
    def dismiss(item_id: int, body: NoteIn, p: Me, conn: Db) -> dict[str, Any]:
        return _decide(item_id, p, conn, "dismissed", lambda: deps.engine.dismiss(conn, item_id, p, body.note))

    @app.get("/api/documents/{doc_id}/file")
    def document_file(doc_id: int, conn: Db) -> Response:
        r = conn.execute("SELECT filename, media_type, storage_key FROM documents WHERE id = %s", (doc_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "Beleg nicht gefunden")
        data = deps.store.get(r["storage_key"])
        return Response(
            data, media_type=r["media_type"], headers={"Content-Disposition": f'inline; filename="{r["filename"]}"'}
        )

    # --- client questions -----------------------------------------------------------------------------

    @app.get("/api/clients/{client_id}/periods/{period}/queries")
    def queries(client_id: str, period: str, conn: Db) -> list[dict[str, Any]]:
        visible_client(conn, client_id)
        qs = conn.execute(
            "SELECT * FROM queries WHERE client_id = %s AND period = %s ORDER BY id", (client_id, _period(period))
        ).fetchall()
        out = []
        for q in qs:
            its = conn.execute(
                """SELECT qi.item_id, qi.reason, qi.question, qi.answer, qi.answered_at, i.state FROM query_items qi JOIN items i ON i.id = qi.item_id
                   WHERE qi.query_id = %s ORDER BY qi.id""",
                (q["id"],),
            ).fetchall()
            out.append(
                {
                    "id": q["id"],
                    "status": q["status"],
                    "subject": q["subject"],
                    "message": q["message"],
                    "sent_at": q["sent_at"],
                    "due_on": q["due_on"],
                    "answered_at": q["answered_at"],
                    "items": [{**dict(i), "reason_label": CLIENT_FLAGS.get(i["reason"], i["reason"])} for i in its],
                }
            )
        return out

    # --- VAT return, sign-off, export -------------------------------------------------------------------

    @app.get("/api/clients/{client_id}/periods/{period}/ustva")
    def ustva(client_id: str, period: str, conn: Db) -> dict[str, Any]:
        visible_client(conn, client_id)
        period = _period(period)
        u = deps.engine.ustva(conn, client_id, period)
        u["checks"] = deps.engine.checks(conn, client_id, period)
        close = conn.execute(
            "SELECT status, signed_by, signed_at, export_sha256 FROM closes WHERE client_id = %s AND period = %s",
            (client_id, period),
        ).fetchone()
        u["close"] = dict(close) if close else {"status": "offen"}
        u["history"] = _ustva_history(conn, client_id, period)
        return u

    def _ustva_history(conn: Conn, client_id: str, period: str) -> list[dict[str, Any]]:
        from kanzlei.engine.close import prev_periods

        out = []
        for hp in prev_periods(period, 12):
            u = deps.engine.ustva(conn, client_id, hp)
            row = {r["kz"]: r for r in u["rows"]}
            out.append(
                {
                    "period": hp,
                    "kz81": row.get("81", {}).get("base_cents", 0),
                    "kz66": row.get("66", {}).get("tax_cents", 0),
                    "kz83": row.get("83", {}).get("tax_cents", 0),
                }
            )
        return out

    @app.post("/api/clients/{client_id}/periods/{period}/sign-off")
    def sign_off(client_id: str, period: str, body: SignOffIn, p: Me, conn: Db) -> dict[str, Any]:
        visible_client(conn, client_id)
        r = deps.engine.sign_off(conn, client_id, _period(period), p, acknowledge_flags=body.acknowledge_flags)
        return {"sha256": r["sha256"], "export": r["export"]}

    @app.get("/api/clients/{client_id}/periods/{period}/export")
    def export(client_id: str, period: str, conn: Db) -> Response:
        visible_client(conn, client_id)
        name, data = deps.engine.export(conn, client_id, _period(period))
        return Response(
            data,
            media_type="text/csv; charset=windows-1252",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/clients/{client_id}/master-export")
    def master_export(client_id: str, conn: Db) -> Response:
        visible_client(conn, client_id)
        name, data = deps.engine.export_master(conn, client_id)
        return Response(
            data,
            media_type="text/csv; charset=windows-1252",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    # --- client portal (no staff login: the token is the key to one bundle) -------------------------------

    def _bundle(token: str) -> list[dict[str, Any]]:
        if len(token) < 20 or len(token) > 64:
            raise HTTPException(404, "Link ungültig")
        with as_system(deps.pool) as conn:
            rows = conn.execute("SELECT * FROM portal_bundle(%s)", (sha256(token.encode()),)).fetchall()
        if not rows:
            raise HTTPException(404, "Link ungültig oder bereits erledigt")
        return [dict(r) for r in rows]

    @app.get("/api/portal/{token}")
    def portal(token: str) -> dict[str, Any]:
        rows = _bundle(token)
        first = rows[0]
        return {
            "client": first["client_name"],
            "firm": first["firm_name"],
            "period": first["period"],
            "due_on": first["due_on"],
            "status": first["status"],
            "items": [
                {
                    "item_id": r["item_id"],
                    "reason": r["reason"],
                    "question": r["question"],
                    "options": r["options"],
                    "answer": r["answer"],
                }
                for r in rows
            ],
        }

    @app.post("/api/portal/{token}/items/{item_id}")
    def portal_answer(token: str, item_id: int, body: AnswerIn) -> dict[str, Any]:
        rows = _bundle(token)
        row = next((r for r in rows if r["item_id"] == item_id), None)
        if row is None:
            raise HTTPException(404, "Frage nicht gefunden")
        ans = {k: v for k, v in body.model_dump().items() if v not in (None, "")}
        if ans.get("choice") == "upload" or not valid_answer(row["reason"], ans):
            raise HTTPException(400, "Bitte eine der Antworten wählen und die Angaben ausfüllen")
        with as_system(deps.pool) as conn:
            ok = conn.execute(
                "SELECT portal_answer(%s, %s, %s) AS ok", (sha256(token.encode()), item_id, Jsonb(ans))
            ).fetchone()
        if not ok or not ok["ok"]:
            raise HTTPException(409, "Diese Fragen sind bereits beantwortet")
        return {"ok": True}

    @app.post("/api/portal/{token}/items/{item_id}/upload")
    async def portal_upload(token: str, item_id: int, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        rows = _bundle(token)
        row = next((r for r in rows if r["item_id"] == item_id), None)
        if row is None or not any(o["value"] == "upload" for o in row["options"]):
            raise HTTPException(404, "Für diese Frage kann kein Beleg hochgeladen werden")
        data = await _read(file)
        with as_system(deps.pool) as conn:
            cid = conn.execute("SELECT client_id FROM items WHERE id = %s", (item_id,)).fetchone()
            assert cid is not None
            r = deps.engine.import_document(
                conn,
                cid["client_id"],
                data,
                file.filename or "beleg.pdf",
                source="portal",
                direction="in",
                actor=SYSTEM,
            )
            ans = {"choice": "upload", "document_id": r["id"]}
            ok = conn.execute(
                "SELECT portal_answer(%s, %s, %s) AS ok", (sha256(token.encode()), item_id, Jsonb(ans))
            ).fetchone()
        if not ok or not ok["ok"]:
            raise HTTPException(409, "Diese Fragen sind bereits beantwortet")
        return {"ok": True, "document": r["id"]}

    # --- the group: rollout across firms ------------------------------------------------------------------

    @app.get("/api/rollout/periods")
    def rollout_periods(p: Me) -> list[str]:
        if p.role not in ("gruppe", "berater"):
            raise HTTPException(403, "Nur für Steuerberater und das Gruppen-Team")
        with as_user(deps.pool, p) as conn:
            return [r["rollout_periods"] for r in conn.execute("SELECT rollout_periods()").fetchall()]

    @app.get("/api/rollout")
    def rollout(p: Me, period: Annotated[str, Query()]) -> dict[str, Any]:
        if p.role not in ("gruppe", "berater"):
            raise HTTPException(403, "Nur für Steuerberater und das Gruppen-Team")
        with as_user(deps.pool, p) as conn:
            firms = [dict(r) for r in conn.execute("SELECT * FROM rollout(%s)", (_period(period),)).fetchall()]
            corrections = conn.execute(
                """SELECT firm_id, from_family, to_family, count(*) AS n FROM corrections
                   WHERE at >= now() - interval '90 days' GROUP BY 1, 2, 3 ORDER BY n DESC LIMIT 12"""
            ).fetchall()
            unmapped = conn.execute(
                "SELECT firm_id, account, name, rows FROM firm_accounts WHERE family IS NULL ORDER BY rows DESC LIMIT 25"
            ).fetchall()
        fams = families()
        for f in firms:
            f["automation_share"] = round(f["auto"] / f["items"], 4) if f["items"] else 0.0
            f["no_touch_share"] = round((f["auto"] + f["by_client"]) / f["items"], 4) if f["items"] else 0.0
        return {
            "period": period,
            "firms": firms,
            "corrections": [
                {
                    **dict(c),
                    "from_label": fams[c["from_family"]].label if c["from_family"] in fams else c["from_family"],
                    "to_label": fams[c["to_family"]].label if c["to_family"] in fams else c["to_family"],
                }
                for c in corrections
            ],
            "unmapped_accounts": [dict(u) for u in unmapped],
        }

    @app.put("/api/firms/{firm_id}/accounts/{account}")
    def map_account(firm_id: str, account: int, body: MapAccountIn, p: Me) -> dict[str, Any]:
        if body.family not in families():
            raise HTTPException(400, "Unbekannte Buchungsfamilie")
        with as_user(deps.pool, p) as conn:
            n = conn.execute(
                "UPDATE firm_accounts SET family = %s, role = %s, tax = %s, mapped_by = %s, mapped_at = now() WHERE firm_id = %s AND account = %s",
                (body.family, body.role, body.tax, p.login, firm_id, account),
            ).rowcount
            if n == 0:
                raise HTTPException(404, "Konto nicht gefunden oder keine Berechtigung")
            event(conn, p.login, "account.map", {"account": account, **body.model_dump()}, firm=firm_id)
        return {"ok": True}

    @app.get("/api/audit/verify")
    def audit(p: Me) -> dict[str, Any]:
        if p.role not in ("berater", "gruppe"):
            raise HTTPException(403)
        with as_user(deps.pool, p) as conn:
            r = conn.execute("SELECT * FROM verify_events()").fetchone()
        assert r is not None
        return {"checked": r["checked"], "intact": r["first_broken"] is None, "first_broken": r["first_broken"]}

    @app.get("/api/evaluation")
    def evaluation(_: Me) -> dict[str, Any]:
        path = deps.settings.reports_dir / "evaluation.json"
        if not path.exists():
            raise HTTPException(404, "Noch keine Auswertung")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    @app.get("/api/version", response_class=PlainTextResponse)
    def version() -> str:
        return hashlib.sha256(str(deps.engine.decision.version).encode()).hexdigest()[:8]

    return app


def _invoice_view(d: dict[str, Any]) -> dict[str, Any]:
    inv = Invoice.from_json(d)
    return {
        "source": inv.source,
        "invoice_no": inv.invoice_no,
        "issue_date": inv.issue_date,
        "delivery_from": inv.delivery_from,
        "seller": inv.seller.name,
        "seller_vat_id": inv.seller.vat_id or inv.seller.tax_no,
        "seller_country": inv.seller.country,
        "buyer": inv.buyer.name,
        "lines": [
            {"description": ln.description, "net_cents": ln.net_cents, "rate": ln.rate, "category": ln.category}
            for ln in inv.lines
        ],
        "taxes": [
            {"category": t.category, "rate": t.rate, "base_cents": t.base_cents, "tax_cents": t.tax_cents}
            for t in inv.taxes
        ],
        "gross_cents": inv.gross_cents,
        "notes": inv.notes,
        "issues": inv.issues,
        "gross_label": fmt_de(inv.gross_cents) if inv.gross_cents is not None else None,
    }


def create_app() -> FastAPI:
    s = settings()
    pool = create_pool(s.database_url)
    store = store_from_url(s.storage_url)
    from kanzlei.config import close_config, config_dir, llm_config

    lc = llm_config()

    def reader_for(_: Any) -> ModelReader | None:
        return ModelReader(lc) if lc.configured else None

    engine = Engine(
        store, Classifier.load(), DecisionModel.load(config_dir() / close_config().decision_model_file), reader_for
    )
    return build_app(Deps(pool=pool, settings=s, engine=engine, store=store))
