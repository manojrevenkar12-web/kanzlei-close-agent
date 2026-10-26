import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";

import { api } from "../../shared/api/client";
import type { DocView, ItemDetailResponse, LineView } from "../../shared/api/types";
import { amount, date, eur, TAX_LABEL } from "../../shared/lib/format";
import { motion as m } from "../../shared/theme/tokens";
import {
  Amount,
  Button,
  ErrorState,
  Notice,
  QueryState,
  SkeletonRows,
  StateBadge,
  Tag,
} from "../../shared/ui";
import { useDecide, useFamilies, useItem } from "./api";
import styles from "./Client.module.css";

export function ItemDetail({
  id,
  clientId,
  period,
  locked,
}: {
  id: number;
  clientId: string;
  period: string;
  locked: boolean;
}) {
  const item = useItem(id);
  return (
    <QueryState query={item} skeleton={<SkeletonRows rows={8} label="Posten wird geladen" />}>
      {(d) => (
        <AnimatePresence mode="wait">
          <motion.article
            key={d.id}
            className={styles.detail}
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: m.base, ease: m.ease }}
          >
            <Detail d={d} clientId={clientId} period={period} locked={locked} />
          </motion.article>
        </AnimatePresence>
      )}
    </QueryState>
  );
}

function Detail({
  d,
  clientId,
  period,
  locked,
}: {
  d: ItemDetailResponse;
  clientId: string;
  period: string;
  locked: boolean;
}) {
  const lines = d.final_lines ?? d.proposal_lines;
  const waitingForClient = d.flags.some((f) => f.client);
  return (
    <>
      <header className={styles.detailHead}>
        <div>
          <h2 className={styles.detailTitle}>{d.counterparty || "ohne Namen"}</h2>
          <p className={styles.detailSub}>
            {d.kind === "invoice" ? "Rechnungseingang" : "Bankumsatz"} vom {date(d.date)}
            {d.iban && `, ${d.iban}`}
          </p>
          {d.remittance && <p className={styles.remittance}>{d.remittance}</p>}
        </div>
        <div className={styles.detailAmount}>
          <Amount cents={d.amount_cents} strong />
          <StateBadge state={d.state} />
        </div>
      </header>

      {d.flags.length > 0 && (
        <div className={styles.flags}>
          {d.flags.map((f) => (
            <Tag key={f.code} tone={f.client ? "client" : "review"}>
              {f.label}
            </Tag>
          ))}
        </div>
      )}

      <section aria-labelledby={`b-${d.id}`}>
        <h3 id={`b-${d.id}`} className={styles.h3}>
          {d.final_lines ? "Gebucht" : "Buchungsvorschlag"}
          {d.family_label && <span className={styles.h3Sub}> {d.family_label}</span>}
        </h3>
        <Journal lines={lines} />
        {!d.final_lines && d.source && (
          <p className={styles.small}>
            Grundlage: {SOURCE[d.source] ?? d.source}
            {d.flags.length === 0 &&
              d.confidence > 0 &&
              `, Wahrscheinlichkeit richtig ${Math.round(d.confidence * 100)} %`}
            {d.flags.length > 0 && ", von einer Regel angehalten"}
          </p>
        )}
        {d.decided_by && <p className={styles.small}>Entschieden von {d.decided_by}</p>}
      </section>

      {d.reasons.length > 0 && (
        <section aria-labelledby={`w-${d.id}`}>
          <h3 id={`w-${d.id}`} className={styles.h3}>
            Warum
          </h3>
          <ul className={styles.reasons}>
            {d.reasons.map((r, i) => (
              <li key={i}>{r.text}</li>
            ))}
          </ul>
        </section>
      )}

      {!locked && (d.state === "review" || d.state === "client") && (
        <Actions d={d} clientId={clientId} period={period} waitingForClient={waitingForClient} />
      )}

      {d.questions.length > 0 && (
        <section aria-labelledby={`q-${d.id}`}>
          <h3 id={`q-${d.id}`} className={styles.h3}>
            Rückfrage an den Mandanten
          </h3>
          {d.questions.map((q, i) => (
            <div key={i} className={styles.question}>
              <p>{q.question}</p>
              <p className={styles.small}>
                {q.answer ? `Antwort: ${answerText(q.answer)}` : "Noch keine Antwort."}
              </p>
            </div>
          ))}
        </section>
      )}

      {d.documents.map((doc) => (
        <Document key={doc.id} doc={doc} />
      ))}
      {d.documents.length === 0 && d.kind === "payment" && (
        <p className={styles.small}>Kein Beleg zugeordnet.</p>
      )}

      {d.history.length > 0 && (
        <section aria-labelledby={`h-${d.id}`}>
          <h3 id={`h-${d.id}`} className={styles.h3}>
            Bisher gebucht
          </h3>
          <table className={styles.mini}>
            <tbody>
              {d.history.map((h, i) => (
                <tr key={i}>
                  <td>{date(h.booking_date)}</td>
                  <td>{h.account}</td>
                  <td>{TAX_LABEL[h.tax] ?? h.tax}</td>
                  <td className={styles.num}>{amount(h.amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}

const SOURCE: Record<string, string> = {
  memory: "Buchungen dieses Mandanten",
  classifier: "Text des Umsatzes und des Belegs",
  document: "Rechnung",
  rule: "Regel",
  conflict: "Text dieses Umsatzes (widerspricht der Historie)",
  answer: "Antwort des Mandanten",
  llm: "Sprachmodell (geprüft)",
  none: "keine",
};

function answerText(a: Record<string, unknown>): string {
  return Object.entries(a)
    .filter(([k]) => k !== "document_id")
    .map(([, v]) => String(v))
    .join(", ");
}

function Journal({ lines }: { lines: LineView[] }) {
  return (
    <table className={styles.journal}>
      <thead>
        <tr>
          <th scope="col">Soll</th>
          <th scope="col">Haben</th>
          <th scope="col">Steuer</th>
          <th scope="col" className={styles.num}>
            Betrag
          </th>
        </tr>
      </thead>
      <tbody>
        {lines.map((ln, i) => (
          <tr key={i}>
            <td>{ln.debit_label}</td>
            <td>{ln.credit_label}</td>
            <td>
              {TAX_LABEL[ln.tax] ?? ln.tax}
              {ln.bu && <span className={styles.bu}> BU {ln.bu}</span>}
            </td>
            <td className={styles.num}>{amount(ln.amount_cents)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Document({ doc }: { doc: DocView }) {
  const inv = doc.invoice;
  const [err, setErr] = useState<string | null>(null);
  const open = async () => {
    try {
      setErr(null);
      await api.download(`/api/documents/${doc.id}/file`, doc.filename);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <section className={styles.doc} aria-label={`Beleg ${doc.filename}`}>
      <div className={styles.docHead}>
        <h3 className={styles.h3}>Beleg</h3>
        <span className={styles.small}>
          {FORMAT[doc.format] ?? doc.format}
          {doc.source === "portal" && ", vom Mandanten nachgereicht"}
        </span>
        <Button size="small" variant="ghost" onClick={() => void open()}>
          Original öffnen
        </Button>
      </div>
      {err && <ErrorState error={new Error(err)} />}
      <dl className={styles.docFacts}>
        <dt>Aussteller</dt>
        <dd>
          {inv.seller || "–"}{" "}
          {inv.seller_vat_id && <span className={styles.small}>({inv.seller_vat_id})</span>}
        </dd>
        <dt>Nummer, Datum</dt>
        <dd>
          {inv.invoice_no ?? "–"}, {date(inv.issue_date)}
          {inv.delivery_from && `, Leistung ${date(inv.delivery_from)}`}
        </dd>
        <dt>Betrag</dt>
        <dd>{inv.gross_cents !== null ? eur(inv.gross_cents) : "nicht lesbar"}</dd>
      </dl>
      {inv.lines.length > 0 && (
        <table className={styles.mini}>
          <tbody>
            {inv.lines.slice(0, 6).map((ln, i) => (
              <tr key={i}>
                <td>{ln.description}</td>
                <td>{ln.category === "S" ? `${ln.rate} %` : (ln.category ?? "")}</td>
                <td className={styles.num}>{ln.net_cents || ln.category ? amount(ln.net_cents) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {inv.notes.length > 0 && <p className={styles.small}>{inv.notes.join(" ")}</p>}
      {inv.issues.length > 0 && <Notice tone="warn">{inv.issues.join(". ")}</Notice>}
    </section>
  );
}

const FORMAT: Record<string, string> = {
  "xrechnung-ubl": "XRechnung (UBL)",
  "xrechnung-cii": "XRechnung (CII)",
  zugferd: "ZUGFeRD",
  pdf: "PDF",
  llm: "PDF, vom Sprachmodell gelesen",
};

function Actions({
  d,
  clientId,
  period,
  waitingForClient,
}: {
  d: ItemDetailResponse;
  clientId: string;
  period: string;
  waitingForClient: boolean;
}) {
  const decide = useDecide(clientId, period);
  const families = useFamilies();
  const [mode, setMode] = useState<"none" | "correct">("none");
  const [family, setFamily] = useState(d.family ?? "");
  const [tax, setTax] = useState("");
  const [reason, setReason] = useState("");
  return (
    <section className={styles.actions} aria-label="Entscheidung">
      {waitingForClient && (
        <p className={styles.small}>
          Wartet auf den Mandanten. Sie können trotzdem selbst entscheiden oder auf das Klärungskonto buchen.
        </p>
      )}
      <div className={styles.actionRow}>
        {d.state === "review" && !waitingForClient && (
          <Button
            variant="primary"
            onClick={() => decide.mutate({ id: d.id, d: { kind: "accept" } })}
            busy={decide.isPending && decide.variables?.d.kind === "accept"}
          >
            Übernehmen
          </Button>
        )}
        <Button
          onClick={() => setMode(mode === "correct" ? "none" : "correct")}
          aria-expanded={mode === "correct"}
        >
          Korrigieren
        </Button>
        {d.kind === "payment" ? (
          <Button
            variant="ghost"
            onClick={() => decide.mutate({ id: d.id, d: { kind: "park", note: "Klärung" } })}
            busy={decide.isPending && decide.variables?.d.kind === "park"}
          >
            Auf Klärungskonto
          </Button>
        ) : (
          <Button
            variant="ghost"
            onClick={() =>
              decide.mutate({ id: d.id, d: { kind: "dismiss", note: "mit der Zahlung buchen" } })
            }
          >
            Nicht als Rechnung buchen
          </Button>
        )}
      </div>
      <AnimatePresence>
        {mode === "correct" && (
          <motion.form
            className={styles.correct}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: m.base, ease: m.ease }}
            onSubmit={(e) => {
              e.preventDefault();
              decide.mutate({ id: d.id, d: { kind: "correct", family, tax: tax || null, reason } });
            }}
          >
            <label>
              Was ist es?
              <select value={family} onChange={(e) => setFamily(e.target.value)} required>
                <option value="" disabled>
                  bitte wählen
                </option>
                {(families.data ?? []).map((f) => (
                  <option key={f.code} value={f.code}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Steuer
              <select value={tax} onChange={(e) => setTax(e.target.value)}>
                <option value="">nach Beleg und Regeln</option>
                {Object.entries(TAX_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.wide}>
              Hinweis für das Team (optional)
              <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
            </label>
            <Button
              type="submit"
              variant="primary"
              busy={decide.isPending && decide.variables?.d.kind === "correct"}
              disabled={!family}
            >
              Korrigiert buchen
            </Button>
          </motion.form>
        )}
      </AnimatePresence>
      {decide.isError && <ErrorState error={decide.error} title="Nicht gebucht" />}
    </section>
  );
}
