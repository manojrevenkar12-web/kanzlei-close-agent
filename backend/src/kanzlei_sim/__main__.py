"""python -m kanzlei_sim <command>

export DIR             firm packages (DATEV history, master data) and the development months
                       as files: bank statements, e-invoices, PDFs
seed                   migrate the database named by KANZLEI_ADMIN_DATABASE_URL and onboard the
                       three firms (history), import July 2026 statements and receipts and run
                       the close, so the app has a month in progress to show
train                  train the classifier and the decision model (writes config/)
evaluate [--sets ..]   close the development months and the blind sets; write reports/
gate                   fail when the release conditions in config/release.yaml are not met
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from kanzlei.config import close_config, config_dir, settings
from kanzlei_sim import evaluate as ev
from kanzlei_sim.run import build_package, records_json
from kanzlei_sim.scenario import Firm, load
from kanzlei_sim.world import DEV, HISTORY, build

ROOT = Path(__file__).resolve().parents[3]
BLIND = Path(__file__).resolve().parent / "blind"


def reports_dir() -> Path:
    return Path(os.environ.get("KANZLEI_REPORTS_DIR", str(ROOT / "reports")))


def admin_url() -> str:
    return os.environ.get("KANZLEI_ADMIN_DATABASE_URL", settings().admin_database_url)


def blind_sets() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for d in sorted(BLIND.iterdir()) if BLIND.exists() else []:
        if d.is_dir() and list(d.glob("*.yaml")):
            out[d.name] = sorted(d.glob("*.yaml"))
    return out


def blind_status(name: str) -> str:
    f = BLIND / name / "STATUS"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "heldout"


def cmd_export(out: Path) -> None:
    firms = build()
    from kanzlei_sim import render
    from kanzlei_sim.run import opening_for

    for f in firms:
        build_package(f, out / "packages" / f.id, HISTORY)
        for c in f.clients:
            for p in DEV:
                d = out / "months" / c.id / p
                (d / "belege").mkdir(parents=True, exist_ok=True)
                xml, _ = render.camt053(c, p, c.months[p], opening_for(c, p))
                (d / f"camt053_{c.mandant_nr}_{p}.xml").write_bytes(xml)
                for e in c.months[p]:
                    if e.document and e.document.arrives == "with_statement":
                        name, data = render.document(c, c.party(e.party), e.document)
                        (d / "belege" / name).write_bytes(data)
    print(f"exported to {out}")


def cmd_train() -> None:
    from kanzlei_sim.train import train_classifier, train_decision

    cfg_dir = config_dir()
    clf = train_classifier(build(), HISTORY, cfg_dir / "classifier.npz")
    print(
        f"classifier: {clf['rows']} rows, {clf['families']} families, unseen-name accuracy {clf['cv_unseen_counterparty_accuracy']}"
    )
    release = yaml.safe_load((cfg_dir / "release.yaml").read_text(encoding="utf-8"))
    results = ev.close_set(admin_url(), "kanzlei_train", build(), HISTORY, DEV, "train", decision=False)
    recs = [r for m in results for r in m.records]
    dec = train_decision(
        recs, cfg_dir / close_config().decision_model_file, float(release["decision"]["max_wrong_share_of_automatic"])
    )
    print(f"decision: threshold {dec['threshold']}, cross-validation {dec['cross_validation']}")
    (reports_dir()).mkdir(parents=True, exist_ok=True)
    (reports_dir() / "training.json").write_text(
        json.dumps(
            {
                "classifier": {k: v for k, v in clf.items() if k != "label_counts"},
                "decision": {k: dec[k] for k in ("threshold", "trained_on", "cross_validation", "version")},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_blind(paths: list[Path]) -> list[Firm]:
    return [load(p) for p in paths]


def cmd_evaluate(sets: list[str]) -> dict[str, Any]:
    reports = reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sets": {},
        "first_runs": {},
    }
    meta = _versions()
    if "dev" in sets:
        res = ev.close_set(admin_url(), "kanzlei_eval_dev", build(), HISTORY, DEV, "dev")
        out["sets"]["dev"] = ev.metrics(res)
        (reports / "failures_dev.json").write_text(
            json.dumps(ev.failures(res), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    for name, paths in blind_sets().items():
        if name not in sets and "blind" not in sets:
            continue
        firms = _load_blind(paths)
        months = sorted({p for f in firms for c in f.clients for p in c.months})
        res = ev.close_set(admin_url(), f"kanzlei_eval_{name.replace('-', '_')}", firms, [], months, name)
        m = ev.metrics(res)
        out["sets"][name] = {**m, "status": blind_status(name)}
        out["first_runs"][name] = ev.record_first_run(reports, name, m, meta)["metrics"]
        if blind_status(name) == "regression":
            (reports / f"failures_{name}.json").write_text(
                json.dumps(ev.failures(res), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        (reports / "blind" / name).mkdir(parents=True, exist_ok=True)
        (reports / "blind" / name / "records.json").write_text(
            json.dumps(records_json(res), ensure_ascii=False) + "\n", encoding="utf-8"
        )
    out["versions"] = meta
    previous = (
        json.loads((reports / "evaluation.json").read_text(encoding="utf-8"))
        if (reports / "evaluation.json").exists()
        else {}
    )
    merged = {
        **previous,
        **out,
        "sets": {**previous.get("sets", {}), **out["sets"]},
        "first_runs": {**previous.get("first_runs", {}), **out["first_runs"]},
    }
    (reports / "evaluation.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in out["sets"].items():
        print(
            k,
            {
                x: v.get(x)
                for x in (
                    "items",
                    "booked_automatically_share",
                    "automatic_wrong",
                    "no_staff_touch_share",
                    "first_proposal_right",
                    "vat_return_exact_months",
                    "signed_off_months",
                )
            },
        )
    return merged


def _versions() -> dict[str, Any]:
    dec = (
        json.loads((config_dir() / close_config().decision_model_file).read_text(encoding="utf-8"))
        if (config_dir() / close_config().decision_model_file).exists()
        else {}
    )
    return {"decision_model": dec.get("version"), "threshold": dec.get("threshold")}


def cmd_gate() -> int:
    release = yaml.safe_load((config_dir() / "release.yaml").read_text(encoding="utf-8"))
    data = json.loads((reports_dir() / "evaluation.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    dev = data["sets"].get("dev")
    g = release["gate"]
    if not dev:
        problems.append("no development evaluation")
    else:
        if dev["automatic_wrong_share"] > g["dev_max_automatic_wrong_share"]:
            problems.append(
                f"dev: wrong automatic bookings {dev['automatic_wrong_share']:.2%} > {g['dev_max_automatic_wrong_share']:.2%}"
            )
        if dev["final_right"] < 1.0:
            problems.append(f"dev: reviewed months not fully right ({dev['final_right']:.2%})")
        if dev["vat_return_exact_months"] < dev["client_months"]:
            problems.append(
                f"dev: VAT return differs from the truth in {dev['client_months'] - dev['vat_return_exact_months']} months"
            )
        if dev["signed_off_months"] < dev["client_months"]:
            problems.append(
                f"dev: {dev['client_months'] - dev['signed_off_months']} months could not be signed off: {dev['sign_off_errors'][:3]}"
            )
    for name, m in data["sets"].items():
        if name == "dev" or m.get("status") != "heldout":
            continue
        first = data["first_runs"].get(name, {})
        if m["automatic_wrong_share"] > max(
            first.get("automatic_wrong_share", 0.0), g["blind_max_automatic_wrong_share"]
        ):
            problems.append(
                f"{name}: wrong automatic bookings {m['automatic_wrong_share']:.2%} worse than the first run and the limit"
            )
        if m["vat_return_exact_months"] < m["client_months"] and m["final_right"] < 1.0:
            problems.append(f"{name}: reviewed months not right")
    if problems:
        print("GATE FAILED\n- " + "\n- ".join(problems))
        return 1
    print("gate passed")
    return 0


def cmd_seed() -> None:
    from kanzlei.db import as_user, create_pool, principal
    from kanzlei.migrate import migrate
    from kanzlei.onboarding import import_package
    from kanzlei.storage import store_from_url
    from kanzlei_sim import render
    from kanzlei_sim.run import opening_for

    s = settings()
    migrate(admin_url(), s.app_db_password)
    pool = create_pool(s.database_url, 4)
    eng = ev.Engine(
        store_from_url(s.storage_url),
        ev.Classifier.load(),
        ev.DecisionModel.load(config_dir() / close_config().decision_model_file),
    )
    firms = build()
    tmp = Path(tempfile.mkdtemp(prefix="kca-seed-"))
    from kanzlei.db import as_system

    period = DEV[0]
    for f in firms:
        build_package(f, tmp / f.id, HISTORY)
        with as_system(pool) as conn:
            import_package(conn, tmp / f.id, actor="seed")
        for c in f.clients:
            who = principal(pool, c.assigned[0])
            assert who is not None
            with as_user(pool, who) as conn:
                xml, _ = render.camt053(c, period, c.months[period], opening_for(c, period))
                eng.import_statement(conn, c.id, xml, f"camt053_{c.mandant_nr}_{period}.xml", who)
                for e in c.months[period]:
                    if e.document and e.document.arrives == "with_statement":
                        name, data = render.document(c, c.party(e.party), e.document)
                        eng.import_document(
                            conn, c.id, data, name, source="upload", direction=e.document.direction, actor=who
                        )
                summary = eng.run(conn, c.id, period, who)
                q = summary.get("query")
                if q:
                    print(f"{c.name}: portal link /portal/{q['token']}")
    pool.close()
    print(f"seeded {len(firms)} firms, month {period} in progress")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kanzlei_sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("dir", type=Path)
    sub.add_parser("seed")
    sub.add_parser("train")
    v = sub.add_parser("evaluate")
    v.add_argument("--sets", default="dev,blind")
    sub.add_parser("gate")
    va = sub.add_parser("validate")
    va.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        from collections import Counter

        from kanzlei_sim.scenario import validate

        bad = 0
        for f in a.files:
            try:
                firm = load(f)
            except Exception as e:
                print(f"{f}: cannot load: {e}")
                bad += 1
                continue
            problems = validate(firm)
            for p in problems:
                print(f"{f}: {p}")
            bad += len(problems)
            for c in firm.clients:
                evs = [e for evs in c.months.values() for e in evs]
                fams = Counter(e.truth.family for e in evs if e.truth)
                print(f"{f.name} {c.id}: {len(evs)} events, {len(c.history)} history lines, families {dict(fams)}")
        return 1 if bad else 0
    if a.cmd == "export":
        cmd_export(a.dir)
    elif a.cmd == "seed":
        cmd_seed()
    elif a.cmd == "train":
        cmd_train()
    elif a.cmd == "evaluate":
        cmd_evaluate([s.strip() for s in a.sets.split(",") if s.strip()])
    elif a.cmd == "gate":
        return cmd_gate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
