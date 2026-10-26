import { motion } from "framer-motion";
import { Link, useSearchParams } from "react-router-dom";

import type { BoardRow } from "../../shared/api/types";
import { date, daysUntil, METHOD, monthLabel, REGIME, shortMonth } from "../../shared/lib/format";
import { motion as m } from "../../shared/theme/tokens";
import { EmptyState, PageHead, QueryState, Runway, SkeletonRows, Tag } from "../../shared/ui";
import { useBoard, usePeriods } from "./api";
import styles from "./Board.module.css";

const STATUS: Record<string, string> = { offen: "Nicht begonnen", in_arbeit: "In Arbeit", freigabe: "Zur Freigabe", festgeschrieben: "Festgeschrieben" };

export default function BoardPage() {
  const periods = usePeriods();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? periods.data?.[0];
  const board = useBoard(period);

  return (
    <>
      <PageHead
        title="Monatsabschluss"
        kicker={period ? monthLabel(period) : undefined}
        lede="Was der Agent gebucht hat, was Sie prüfen und was beim Mandanten liegt, je Mandant. Festgeschrieben wird von der Steuerberatung."
        actions={
          periods.data && periods.data.length > 1 ? (
            <div className={styles.months} role="tablist" aria-label="Monat">
              {periods.data.slice(0, 6).map((p) => (
                <button key={p} role="tab" aria-selected={p === period} className={p === period ? styles.monthOn : styles.month} onClick={() => setParams({ period: p })}>
                  {shortMonth(p)}
                </button>
              ))}
            </div>
          ) : undefined
        }
      />
      <QueryState
        query={periods}
        skeleton={<SkeletonRows label="Monate werden geladen" />}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="Noch keine Kontoauszüge">Sobald ein Kontoauszug importiert ist, erscheint der Monat hier.</EmptyState>}
      >
        {() => (
          <QueryState
            query={board}
            skeleton={<SkeletonRows rows={8} label="Mandanten werden geladen" />}
            isEmpty={(d) => d.length === 0}
            empty={<EmptyState title="Keine Mandanten">Ihnen sind für diesen Monat keine Mandanten zugeordnet.</EmptyState>}
          >
            {(rows) => <Board rows={rows} period={period ?? ""} />}
          </QueryState>
        )}
      </QueryState>
    </>
  );
}

function Board({ rows, period }: { rows: BoardRow[]; period: string }) {
  const items = rows.reduce((a, r) => a + r.items, 0);
  const auto = rows.reduce((a, r) => a + r.auto, 0);
  const review = rows.reduce((a, r) => a + r.open_review, 0);
  const client = rows.reduce((a, r) => a + r.open_client, 0);
  const signed = rows.filter((r) => r.status === "festgeschrieben").length;
  return (
    <>
      <p className={styles.summary}>
        <strong>{items}</strong> Posten bei {rows.length} Mandanten. Der Agent hat <strong>{auto}</strong> davon selbst gebucht;{" "}
        <strong>{review}</strong> warten auf Ihre Prüfung, <strong>{client}</strong> auf Antworten der Mandanten. {signed} von {rows.length} Monaten sind festgeschrieben.
      </p>
      <div className={styles.table} role="table" aria-label={`Mandanten ${monthLabel(period)}`}>
        <div className={styles.head} role="row">
          <span role="columnheader">Mandant</span>
          <span role="columnheader">Stand</span>
          <span role="columnheader">Offen</span>
          <span role="columnheader">UStVA fällig</span>
          <span role="columnheader">Status</span>
        </div>
        {rows.map((r, i) => (
          <motion.div key={r.id} role="row" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * m.stagger, duration: m.base }}>
            <Link to={`/mandanten/${r.id}/${period}`} className={styles.row} aria-label={`${r.name} öffnen`}>
              <span role="cell" className={styles.client}>
                <span className={styles.name}>{r.name}</span>
                <span className={styles.meta}>
                  Nr. {r.mandant_nr}, {METHOD[r.booking_method]}, {REGIME[r.vat_regime]}
                </span>
              </span>
              <span role="cell" className={styles.progress}>
                <Runway
                  label="Stand"
                  total={r.items}
                  counts={{ auto: r.auto, done: r.reviewed, client: r.open_client, review: r.open_review, parked: r.parked }}
                />
                <span className={styles.progressText}>
                  {r.items === 0 ? "noch nicht gestartet" : `${r.auto + r.reviewed + r.by_client} von ${r.items} gebucht`}
                </span>
              </span>
              <span role="cell" className={styles.open}>
                {r.open_review > 0 && <Tag tone="review">{r.open_review} prüfen</Tag>}
                {r.open_client > 0 && <Tag tone="client">{r.open_client} Mandant</Tag>}
                {r.unprocessed > 0 && <Tag>{r.unprocessed} neu</Tag>}
                {r.open_review + r.open_client + r.unprocessed === 0 && <span className={styles.none}>nichts</span>}
              </span>
              <span role="cell" className={styles.due}>
                {r.files_vat_this_month ? <Due iso={r.due_on} /> : <span className={styles.none}>Quartalsmelder</span>}
              </span>
              <span role="cell">
                <span className={r.status === "festgeschrieben" ? styles.statusDone : styles.status}>{STATUS[r.status]}</span>
              </span>
            </Link>
          </motion.div>
        ))}
      </div>
    </>
  );
}

function Due({ iso }: { iso: string }) {
  const d = daysUntil(iso);
  return (
    <span>
      {date(iso)}
      <span className={d < 0 ? styles.late : d <= 5 ? styles.soon : styles.dueIn}>{d < 0 ? ` (${-d} Tage drüber)` : ` (in ${d} Tagen)`}</span>
    </span>
  );
}
