import type { QueryBundle } from "../../shared/api/types";
import { date } from "../../shared/lib/format";
import { Button, EmptyState, Notice, QueryState, SkeletonRows, Tag } from "../../shared/ui";
import { useApplyAnswers, useQueries } from "./api";
import styles from "./Client.module.css";

const STATUS: Record<QueryBundle["status"], string> = {
  offen: "Wartet auf Antwort",
  beantwortet: "Beantwortet",
  geschlossen: "Erledigt",
};

export function QueriesTab({ clientId, period }: { clientId: string; period: string }) {
  const queries = useQueries(clientId, period);
  const apply = useApplyAnswers(clientId, period);
  return (
    <QueryState
      query={queries}
      skeleton={<SkeletonRows rows={5} label="Rückfragen werden geladen" />}
      isEmpty={(d) => d.length === 0}
      empty={
        <EmptyState title="Keine Rückfragen">
          Der Agent fragt den Mandanten nur, was in den Unterlagen fehlt: Belege, Anlässe von Bewirtungen,
          private oder betriebliche Zahlungen.
        </EmptyState>
      }
    >
      {(list) => {
        const waiting = list.flatMap((q) => q.items).filter((i) => i.answer && i.state === "client").length;
        return (
          <div className={styles.queries}>
            {waiting > 0 && (
              <Notice tone="info">
                {waiting} {waiting === 1 ? "Antwort liegt" : "Antworten liegen"} vor.{" "}
                <Button size="small" variant="primary" onClick={() => apply.mutate()} busy={apply.isPending}>
                  Antworten übernehmen
                </Button>
              </Notice>
            )}
            {apply.isSuccess && (
              <Notice tone="ok">
                {apply.data.applied} Antworten übernommen und nach den Regeln gebucht oder zur Prüfung gelegt.
              </Notice>
            )}
            {list.map((q) => (
              <article key={q.id} className={styles.bundle} aria-label={q.subject}>
                <header className={styles.bundleHead}>
                  <h3 className={styles.h3}>{q.subject}</h3>
                  <Tag tone={q.status === "offen" ? "client" : "plain"}>{STATUS[q.status]}</Tag>
                  <span className={styles.small}>
                    verschickt {date(q.sent_at)}, Antwort bis {date(q.due_on)}
                  </span>
                </header>
                <ol className={styles.bundleItems}>
                  {q.items.map((i) => (
                    <li key={i.item_id}>
                      <p>{i.question}</p>
                      <p className={styles.small}>
                        {i.answer
                          ? `Antwort: ${Object.values(i.answer)
                              .filter((v) => typeof v === "string")
                              .join(", ")}`
                          : "offen"}
                      </p>
                    </li>
                  ))}
                </ol>
                <details className={styles.mail}>
                  <summary>Nachricht an den Mandanten</summary>
                  <pre>{q.message}</pre>
                </details>
              </article>
            ))}
          </div>
        );
      }}
    </QueryState>
  );
}
