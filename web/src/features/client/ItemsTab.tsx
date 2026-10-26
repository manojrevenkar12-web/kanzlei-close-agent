import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

import type { ItemSummary } from "../../shared/api/types";
import { date } from "../../shared/lib/format";
import { motion as m, STATE_LABEL, type ItemState } from "../../shared/theme/tokens";
import { Amount, EmptyState, Kbd, QueryState, SkeletonRows, StateBadge, Tag } from "../../shared/ui";
import { useDecide, useItems } from "./api";
import styles from "./Client.module.css";
import { ItemDetail } from "./ItemDetail";

type Filter = "offen" | ItemState | "alle";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "offen", label: "Offen" },
  { key: "review", label: STATE_LABEL.review },
  { key: "client", label: STATE_LABEL.client },
  { key: "auto", label: STATE_LABEL.auto },
  { key: "done", label: STATE_LABEL.done },
  { key: "parked", label: STATE_LABEL.parked },
  { key: "alle", label: "Alle" },
];

function matches(i: ItemSummary, f: Filter): boolean {
  if (f === "alle") return true;
  if (f === "offen") return i.state === "review" || i.state === "client";
  return i.state === f;
}

export function ItemsTab({
  clientId,
  period,
  locked,
}: {
  clientId: string;
  period: string;
  locked: boolean;
}) {
  const items = useItems(clientId, period);
  const decide = useDecide(clientId, period);
  const [filter, setFilter] = useState<Filter>("offen");
  const [selected, setSelected] = useState<number | null>(null);
  const list = useMemo(
    () => (items.data?.items ?? []).filter((i) => matches(i, filter)),
    [items.data, filter],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of FILTERS) c[f.key] = (items.data?.items ?? []).filter((i) => matches(i, f.key)).length;
    return c;
  }, [items.data]);

  const current = selected !== null && list.some((i) => i.id === selected) ? selected : (list[0]?.id ?? null);

  // Keyboard: j/k move, a accepts a proposal under review.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      const idx = list.findIndex((i) => i.id === current);
      if (e.key === "j" && idx < list.length - 1) setSelected(list[idx + 1]?.id ?? null);
      if (e.key === "k" && idx > 0) setSelected(list[idx - 1]?.id ?? null);
      if (e.key === "a" && current !== null && !locked) {
        const it = list[idx];
        if (it?.state === "review" && !it.flags.some((f) => f.client))
          decide.mutate({ id: current, d: { kind: "accept" } });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list, current, decide, locked]);

  return (
    <QueryState
      query={items}
      skeleton={<SkeletonRows rows={10} label="Posten werden geladen" />}
      isEmpty={(d) => d.items.length === 0}
      empty={
        <EmptyState title="Noch keine Posten">
          Laden Sie den Kontoauszug des Monats hoch (CAMT.053) und führen Sie den Abschluss aus. Belege können
          vorher oder später kommen.
        </EmptyState>
      }
    >
      {() => (
        <div className={styles.workspace}>
          <section className={styles.listPane} aria-label="Posten">
            <div className={styles.filters} role="tablist" aria-label="Filter">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  role="tab"
                  aria-selected={filter === f.key}
                  className={filter === f.key ? styles.filterOn : styles.filter}
                  onClick={() => setFilter(f.key)}
                >
                  {f.label} <span className={styles.count}>{counts[f.key]}</span>
                </button>
              ))}
            </div>
            {list.length === 0 ? (
              <EmptyState title={filter === "offen" ? "Nichts mehr offen" : "Keine Posten in dieser Ansicht"}>
                {filter === "offen"
                  ? "Alle Posten sind gebucht oder geparkt. Weiter mit der Umsatzsteuer und der Freigabe."
                  : "Wählen Sie einen anderen Filter."}
              </EmptyState>
            ) : (
              <ol className={styles.list}>
                {list.map((i, n) => (
                  <motion.li
                    key={i.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: Math.min(n, 20) * m.stagger, duration: m.base }}
                  >
                    <button
                      type="button"
                      className={i.id === current ? styles.rowOn : styles.row}
                      aria-current={i.id === current || undefined}
                      onClick={() => setSelected(i.id)}
                    >
                      <span className={styles.rowDate}>{date(i.date)}</span>
                      <span className={styles.rowMain}>
                        <span className={styles.rowName}>{i.counterparty || "ohne Namen"}</span>
                        <span className={styles.rowSub}>
                          {i.kind === "invoice" ? "Rechnungseingang" : (i.family_label ?? "kein Vorschlag")}
                        </span>
                      </span>
                      <Amount cents={i.amount_cents} />
                      <span className={styles.rowState}>
                        <StateBadge state={i.state} />
                        {i.flags.slice(0, 1).map((f) => (
                          <Tag key={f.code} tone={f.client ? "client" : "review"}>
                            {f.label}
                          </Tag>
                        ))}
                      </span>
                    </button>
                  </motion.li>
                ))}
              </ol>
            )}
            <p className={styles.keys}>
              <Kbd>j</Kbd> <Kbd>k</Kbd> blättern, <Kbd>a</Kbd> Vorschlag übernehmen
            </p>
          </section>
          <section className={styles.detailPane} aria-label="Posten im Detail">
            {current === null ? (
              <EmptyState title="Kein Posten gewählt" />
            ) : (
              <ItemDetail id={current} clientId={clientId} period={period} locked={locked} />
            )}
          </section>
        </div>
      )}
    </QueryState>
  );
}
