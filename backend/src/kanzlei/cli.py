"""kanzlei migrate | onboard DIR | serve | worker | verify-audit"""

from __future__ import annotations

import argparse
import json
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path

from kanzlei.config import settings


def send_outbox(once: bool = False, interval: float = 30.0) -> int:
    """Sends client question emails. Rows are claimed with SKIP LOCKED, so several workers can run.
    Without KANZLEI_SMTP_HOST the message is logged instead (development)."""
    import os

    from kanzlei.db import as_system, create_pool

    s = settings()
    pool = create_pool(s.database_url, 2)
    host = os.environ.get("KANZLEI_SMTP_HOST")
    sender = os.environ.get("KANZLEI_MAIL_FROM", "buchhaltung@kanzlei.example")
    sent = 0
    while True:
        with as_system(pool) as conn:
            rows = conn.execute(
                "SELECT id, to_email, subject, body FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 20 FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for r in rows:
                if host:
                    msg = EmailMessage()
                    msg["From"], msg["To"], msg["Subject"] = sender, r["to_email"], r["subject"]
                    msg.set_content(r["body"])
                    with smtplib.SMTP(host, int(os.environ.get("KANZLEI_SMTP_PORT", "587")), timeout=20) as smtp:
                        smtp.starttls()
                        if os.environ.get("KANZLEI_SMTP_USER"):
                            smtp.login(os.environ["KANZLEI_SMTP_USER"], os.environ.get("KANZLEI_SMTP_PASSWORD", ""))
                        smtp.send_message(msg)
                else:
                    print(json.dumps({"outbox": r["id"], "to": r["to_email"], "subject": r["subject"]}), flush=True)
                conn.execute("UPDATE outbox SET sent_at = now() WHERE id = %s", (r["id"],))
                sent += 1
        if once:
            break
        time.sleep(interval)
    pool.close()
    return sent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kanzlei")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    on = sub.add_parser("onboard", help="import a firm package (firm.json + DATEV EXTF files)")
    on.add_argument("dir", type=Path)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    wk = sub.add_parser("worker")
    wk.add_argument("--once", action="store_true")
    sub.add_parser("verify-audit")
    a = ap.parse_args(argv)
    s = settings()
    if a.cmd == "migrate":
        from kanzlei.migrate import migrate

        print(json.dumps({"applied": migrate(s.admin_database_url, s.app_db_password)}))
    elif a.cmd == "onboard":
        from kanzlei.db import as_system, create_pool
        from kanzlei.onboarding import import_package

        pool = create_pool(s.database_url, 2)
        with as_system(pool) as conn:
            print(json.dumps(import_package(conn, a.dir, actor="cli"), indent=2, ensure_ascii=False, default=str))
        pool.close()
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("kanzlei.api.app:create_app", factory=True, host=a.host, port=a.port, proxy_headers=True)
    elif a.cmd == "worker":
        print(json.dumps({"sent": send_outbox(once=a.once)}))
    elif a.cmd == "verify-audit":
        from kanzlei.db import as_system, create_pool

        pool = create_pool(s.database_url, 1)
        with as_system(pool) as conn:
            r = conn.execute("SELECT * FROM verify_events()").fetchone()
        pool.close()
        assert r is not None
        print(json.dumps({"checked": r["checked"], "first_broken": r["first_broken"]}))
        return 0 if r["first_broken"] is None else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
