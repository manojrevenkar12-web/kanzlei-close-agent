"""Measures a set of closed months against the truth and writes reports/.

The first run of every blind set is recorded once (reports/blind/<set>/FIRST_RUN.json) and never
rewritten; later runs are reported next to it.
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from kanzlei.config import close_config, config_dir
from kanzlei.db import Pool, create_pool
from kanzlei.engine.classifier import Classifier
from kanzlei.engine.close import Engine
from kanzlei.engine.decision import DecisionModel
from kanzlei.migrate import migrate
from kanzlei.storage import LocalStore
from kanzlei_sim.run import MonthResult, Record, run_months, seed
from kanzlei_sim.scenario import Firm


def _url(admin: str, db: str, user: str | None = None, password: str | None = None) -> str:
    from urllib.parse import urlsplit, urlunsplit

    u = urlsplit(admin)
    netloc = u.netloc
    if user:
        netloc = f"{user}:{password}@{netloc.split('@')[-1]}"
    return urlunsplit((u.scheme, netloc, f"/{db}", u.query, u.fragment))


@contextmanager
def fresh_database(admin: str, name: str) -> Iterator[Pool]:
    with psycopg.connect(_url(admin, "postgres"), autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {name}")
    migrate(_url(admin, name), "kanzlei_app")
    pool = create_pool(_url(admin, name, "kanzlei_app", "kanzlei_app"), 4)
    try:
        yield pool
    finally:
        pool.close()


def engine_for(store_dir: Path, *, decision: bool = True) -> Engine:
    model = (
        DecisionModel.load(config_dir() / close_config().decision_model_file)
        if decision
        else DecisionModel.load(Path("/nonexistent"))
    )
    return Engine(LocalStore(store_dir), Classifier.load(), model)


def close_set(
    admin: str,
    db: str,
    firms: list[Firm],
    history: list[str],
    months: list[str],
    set_name: str,
    *,
    decision: bool = True,
) -> list[MonthResult]:
    with fresh_database(admin, db) as pool:
        tmp = Path(tempfile.mkdtemp(prefix=f"kca-{set_name}-"))
        seed(pool, firms, tmp / "packages", history)
        return run_months(engine_for(tmp / "documents", decision=decision), pool, firms, months, set_name)


def _ustva_exact(m: MonthResult) -> bool:
    rows = {r["kz"]: r for r in m.ustva_engine["rows"]}
    for kz, v in m.ustva_truth.items():
        r = rows.get(kz, {"base_cents": 0, "tax_cents": 0})
        if r["base_cents"] != v["base_cents"] or r["tax_cents"] != v["tax_cents"]:
            return False
    return all(kz in m.ustva_truth or (r["base_cents"] == 0 and r["tax_cents"] == 0) for kz, r in rows.items())


def metrics(results: list[MonthResult]) -> dict[str, Any]:
    recs: list[Record] = [r for m in results for r in m.records]
    n = len(recs)
    if not n:
        return {"items": 0}
    autos = [r for r in recs if r.first_route == "auto"]
    auto_wrong = [r for r in autos if not r.first_correct]
    reviewed = [r for r in recs if r.path in ("accepted", "corrected", "manual")]
    asked = [r for r in recs if r.questions]
    q_total = sum(len(r.questions) for r in recs)
    q_needed = sum(sum(r.question_needed) for r in recs)
    by_client_answer = [r for r in recs if r.path == "client"]
    eff = close_config().effort
    minutes = (
        len([r for r in recs if r.path == "accepted"]) * eff["accept"]
        + len([r for r in recs if r.path in ("corrected", "manual")]) * eff["correct"]
        + q_total * eff["query_item"]
        + len(by_client_answer) * eff["answer_review"]
    )
    manual = n * eff["manual_item"]
    fam = defaultdict(lambda: [0, 0])
    for r in recs:
        fam[r.truth_family][0] += int(r.first_correct)
        fam[r.truth_family][1] += 1
    months = len(results)
    final_known = [r for r in recs if r.final_correct is not None]
    no_staff_wrong = [r for r in recs if r.path in ("auto", "client") and r.final_correct is False]
    return {
        "items": n,
        "client_months": months,
        "booked_automatically": len(autos),
        "booked_automatically_share": round(len(autos) / n, 4),
        "automatic_wrong": len(auto_wrong),
        "automatic_wrong_share": round(len(auto_wrong) / len(autos), 4) if autos else 0.0,
        "resolved_by_client_answer": len(by_client_answer),
        # Everything no person looked at: booked alone, or booked by the rules after a client's answer.
        "no_staff_wrong": len(no_staff_wrong),
        "no_staff_wrong_share": round(len(no_staff_wrong) / (len(autos) + len(by_client_answer)), 4)
        if autos or by_client_answer
        else 0.0,
        "no_staff_touch_share": round((len(autos) + len(by_client_answer)) / n, 4),
        "reviewed": len(reviewed),
        "review_proposal_right": round(len([r for r in reviewed if r.path == "accepted"]) / len(reviewed), 4)
        if reviewed
        else 0.0,
        "first_proposal_right": round(sum(r.first_correct for r in recs) / n, 4),
        "corrected": len([r for r in recs if r.path == "corrected"]),
        "booked_by_hand": len([r for r in recs if r.path == "manual"]),
        "client_questions": q_total,
        "items_with_questions": len(asked),
        "questions_needed_share": round(q_needed / q_total, 4) if q_total else 0.0,
        "parked": len([r for r in recs if r.path == "parked"]),
        "final_right": round(sum(1 for r in final_known if r.final_correct) / len(final_known), 4)
        if final_known
        else 0.0,
        "vat_return_exact_months": sum(1 for m in results if _ustva_exact(m)),
        "signed_off_months": sum(1 for m in results if m.signed),
        "sign_off_errors": [m.error for m in results if m.error],
        "staff_minutes_estimate": round(minutes, 1),
        "manual_minutes_estimate": round(manual, 1),
        "first_proposal_right_by_family": {
            k: f"{a}/{b}" for k, (a, b) in sorted(fam.items(), key=lambda kv: -kv[1][1])
        },
        "auto_wrong_examples": [
            {"client": r.client, "event": r.event, "truth": r.truth_family, "proposed": r.family, "source": r.source}
            for r in auto_wrong[:20]
        ],
        "sources": dict(Counter(r.source for r in recs)),
    }


def failures(results: list[MonthResult]) -> list[dict[str, Any]]:
    return [
        {
            "client": r.client,
            "period": r.period,
            "event": r.event,
            "truth": r.truth_family,
            "proposed": r.family,
            "route": r.first_route,
            "flags": r.flags,
            "source": r.source,
            "confidence": round(r.confidence, 3),
        }
        for m in results
        for r in m.records
        if not r.first_correct
    ]


def record_first_run(reports: Path, set_name: str, m: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    path = reports / "blind" / set_name / "FIRST_RUN.json"
    if path.exists():
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"set": set_name, "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"), **meta, "metrics": m}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data
