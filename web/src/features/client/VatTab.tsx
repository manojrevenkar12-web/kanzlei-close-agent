import { useState } from "react";

import { api } from "../../shared/api/client";
import type { Ustva } from "../../shared/api/types";
import { amount, date, euros, shortMonth } from "../../shared/lib/format";
import { useSession } from "../../shared/lib/session";
import { Button, ErrorState, Notice, QueryState, SkeletonRows, Stamp } from "../../shared/ui";
import { useSignOff, useUstva } from "./api";
import styles from "./Client.module.css";

export function VatTab({ clientId, period }: { clientId: string; period: string }) {
  const ustva = useUstva(clientId, period);
  return (
    <QueryState query={ustva} skeleton={<SkeletonRows rows={8} label="Umsatzsteuer wird berechnet" />}>
      {(u) => <Vat u={u} clientId={clientId} period={period} />}
    </QueryState>
  );
}

function Vat({ u, clientId, period }: { u: Ustva; clientId: string; period: string }) {
  const s = useSession();
  const signOff = useSignOff(clientId, period);
  const [ack, setAck] = useState(false);
  const [dlError, setDlError] = useState<string | null>(null);
  const signed = u.close.status === "festgeschrieben";
  const open = u.checks.open_review + u.checks.open_client;
  const rows = u.rows.filter((r) => r.kz !== "83");
  const kz83 = u.rows.find((r) => r.kz === "83");

  const download = async () => {
    try {
      setDlError(null);
      await api.download(`/api/clients/${clientId}/periods/${period}/export`, `EXTF_${period}.csv`);
    } catch (e) {
      setDlError((e as Error).message);
    }
  };

  return (
    <div className={styles.vat}>
      <section className={styles.vatSheet} aria-label="Umsatzsteuer-Voranmeldung">
        <Stamp show={signed} label="Festgeschrieben" sub={u.close.signed_at ? `${date(u.close.signed_at)}, ${u.close.signed_by ?? ""}` : undefined} />
        <h2 className={styles.h2}>Umsatzsteuer-Voranmeldung</h2>
        <p className={styles.small}>
          {u.kleinunternehmer
            ? "Kleinunternehmer (§ 19 UStG): keine Voranmeldung."
            : u.files_this_month
              ? `Abgabe bis ${date(u.due_on)}.`
              : "Quartalsmelder: diese Zahlen fließen in die Quartalsanmeldung."}{" "}
          Bemessungsgrundlagen in vollen Euro, Steuer in Euro und Cent.
        </p>
        <table className={styles.vatTable}>
          <thead>
            <tr>
              <th scope="col">Kz</th>
              <th scope="col">Bezeichnung</th>
              <th scope="col" className={styles.num}>
                Bemessungsgrundlage
              </th>
              <th scope="col" className={styles.num}>
                Steuer
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className={styles.small}>
                  Keine umsatzsteuerlichen Buchungen in diesem Monat.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.kz}>
                <td>{r.kz}</td>
                <td>{r.label}</td>
                <td className={styles.num}>{r.base_cents ? euros(r.base_euros) : ""}</td>
                <td className={styles.num}>{r.tax_cents ? amount(r.tax_cents) : ""}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>83</td>
              <td>{(kz83?.tax_cents ?? 0) >= 0 ? "Vorauszahlung" : "Überschuss (Erstattung)"}</td>
              <td />
              <td className={`${styles.num} ${styles.total}`}>{amount(kz83?.tax_cents ?? 0)}</td>
            </tr>
          </tfoot>
        </table>
        <Trend history={u.history} current={kz83?.tax_cents ?? 0} period={period} />
      </section>

      <aside className={styles.vatSide} aria-label="Freigabe">
        <h2 className={styles.h2}>Freigabe</h2>
        <ul className={styles.checks}>
          <li className={open === 0 ? styles.ok : styles.notOk}>{open === 0 ? "Alle Posten gebucht oder geparkt" : `${open} Posten offen (${u.checks.open_review} Prüfung, ${u.checks.open_client} Mandant)`}</li>
          <li className={u.checks.bank_reconciled ? styles.ok : styles.notOk}>
            {u.checks.bank_reconciled ? "Bank abgestimmt" : `Bank nicht abgestimmt (${amount(u.checks.bank_difference_cents)} €)`}
          </li>
          <li className={u.flags.length === 0 ? styles.ok : styles.warnItem}>{u.flags.length === 0 ? "Keine Auffälligkeiten gegenüber den Vormonaten" : `${u.flags.length} Auffälligkeiten`}</li>
        </ul>
        {u.flags.map((f) => (
          <Notice key={f.kz} tone="warn">
            {f.text}
          </Notice>
        ))}
        {signed ? (
          <>
            <p className={styles.small}>Export-Prüfsumme {u.close.export_sha256?.slice(0, 16)}…</p>
            <Button variant="primary" onClick={() => void download()}>
              DATEV-Export (EXTF)
            </Button>
          </>
        ) : s?.user.can_sign_off ? (
          <>
            {u.flags.length > 0 && (
              <label className={styles.ack}>
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                Auffälligkeiten geprüft
              </label>
            )}
            <Button variant="primary" disabled={open > 0 || !u.checks.bank_reconciled || (u.flags.length > 0 && !ack)} busy={signOff.isPending} onClick={() => signOff.mutate(ack)}>
              Monat festschreiben
            </Button>
            <p className={styles.small}>Danach sind die Buchungen unveränderbar (GoBD). Korrekturen gehen in einen offenen Monat.</p>
          </>
        ) : (
          <p className={styles.small}>Festgeschrieben wird von der Steuerberatung.</p>
        )}
        {signOff.isError && <ErrorState error={signOff.error} title="Nicht festgeschrieben" />}
        {dlError && <ErrorState error={new Error(dlError)} title="Export fehlgeschlagen" />}
      </aside>
    </div>
  );
}

/** Kz 83 over the last twelve months next to this one: the advisor's first plausibility look. */
function Trend({ history, current, period }: { history: Ustva["history"]; current: number; period: string }) {
  const points = [...history.map((h) => ({ p: h.period, v: h.kz83 })), { p: period, v: current }];
  const max = Math.max(1, ...points.map((x) => Math.abs(x.v)));
  return (
    <figure className={styles.trend}>
      <figcaption className={styles.small}>Kz 83 der letzten zwölf Monate und dieses Monats</figcaption>
      <div className={styles.bars} role="img" aria-label={points.map((x) => `${shortMonth(x.p)}: ${amount(x.v)} €`).join(", ")}>
        {points.map((x) => (
          <div key={x.p} className={styles.barCol} title={`${shortMonth(x.p)}: ${amount(x.v)} €`}>
            <div className={x.p === period ? styles.barNow : x.v < 0 ? styles.barNeg : styles.bar} style={{ height: `${Math.max(2, (Math.abs(x.v) / max) * 100)}%` }} />
          </div>
        ))}
      </div>
    </figure>
  );
}
