import type { UseQueryResult } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";

import { amount as fmtAmount } from "../lib/format";
import { motion as m, STATE_LABEL, STATES, type ItemState } from "../theme/tokens";
import styles from "./ui.module.css";

type Variant = "default" | "primary" | "ghost" | "danger";

export function Button({
  variant = "default",
  size,
  busy,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "small"; busy?: boolean }) {
  const cls = [styles.button, variant !== "default" && styles[variant], size && styles[size], className].filter(Boolean).join(" ");
  return (
    <button type="button" {...rest} className={cls} disabled={busy || rest.disabled} aria-busy={busy || undefined}>
      {busy && <span className={styles.spinner} aria-hidden />}
      {children}
    </button>
  );
}

export function Skeleton({ height = "1rem", width = "100%" }: { height?: string; width?: string }) {
  return <div className={styles.skeleton} style={{ height, width } as CSSProperties} aria-hidden />;
}

export function SkeletonRows({ rows = 6, label }: { rows?: number; label: string }) {
  return (
    <div className={styles.skeletons} role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height="2.25rem" width={i === rows - 1 ? "70%" : "100%"} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <section className={styles.state}>
      <h2 className={styles.stateTitle}>{title}</h2>
      {children && <p className={styles.stateBody}>{children}</p>}
      {action}
    </section>
  );
}

export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const message = error instanceof Error ? error.message : "Unbekannter Fehler";
  return (
    <section className={`${styles.state} ${styles.error}`} role="alert">
      <h2 className={styles.stateTitle}>{title ?? "Das hat nicht geklappt"}</h2>
      <p className={styles.stateBody}>{message}</p>
      {onRetry && (
        <Button size="small" onClick={onRetry}>
          Erneut versuchen
        </Button>
      )}
    </section>
  );
}

/** Loading skeleton, error with retry, empty state or content: every query on every screen. */
export function QueryState<T>({
  query,
  skeleton,
  isEmpty,
  empty,
  children,
}: {
  query: UseQueryResult<T>;
  skeleton: ReactNode;
  isEmpty?: (d: T) => boolean;
  empty?: ReactNode;
  children: (d: T) => ReactNode;
}) {
  if (query.isPending) return <>{skeleton}</>;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (isEmpty?.(query.data) && empty) return <>{empty}</>;
  return <>{children(query.data)}</>;
}

const STATE_CLASS: Record<ItemState, string | undefined> = {
  auto: styles.auto,
  done: styles.done,
  client: styles.client,
  review: styles.review,
  parked: styles.parked,
};

export function StateBadge({ state }: { state: ItemState }) {
  return <span className={`${styles.badge} ${STATE_CLASS[state]}`}>{STATE_LABEL[state]}</span>;
}

export function Tag({ children, tone }: { children: ReactNode; tone?: "client" | "review" | "plain" }) {
  const cls = tone === "client" ? styles.client : tone === "review" ? styles.review : "";
  return <span className={`${styles.tag} ${cls}`}>{children}</span>;
}

/** Money in the journal's colours: going out in red ink. */
export function Amount({ cents, strong }: { cents: number; strong?: boolean }) {
  return (
    <span className={`${styles.amount} ${cents < 0 ? styles.haben : ""} ${strong ? styles.strong : ""}`}>
      {cents < 0 ? "−" : ""}
      {fmtAmount(Math.abs(cents))}
      <span className={styles.currency}> €</span>
    </span>
  );
}

/** The month's runway: how much is booked by the agent, checked by staff, waiting on the
 * client, still to check, or parked. The one graphic the board is built around. */
export function Runway({ counts, total, label }: { counts: Partial<Record<ItemState, number>>; total: number; label: string }) {
  const parts = STATES.map((s) => ({ s, n: counts[s] ?? 0 })).filter((p) => p.n > 0);
  const title = parts.map((p) => `${STATE_LABEL[p.s]}: ${p.n}`).join(", ");
  return (
    <div className={styles.runway} role="img" aria-label={`${label}: ${title || "keine Posten"}`} title={title}>
      {total === 0 ? (
        <div className={styles.runwayEmpty} />
      ) : (
        parts.map((p, i) => (
          <motion.div
            key={p.s}
            className={`${styles.runwayPart} ${STATE_CLASS[p.s]}`}
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ duration: m.slow, ease: m.ease, delay: i * m.stagger }}
            style={{ flexGrow: p.n, transformOrigin: "left" }}
          />
        ))
      )}
    </div>
  );
}

export function PageHead({ title, lede, actions, kicker }: { title: string; lede?: ReactNode; actions?: ReactNode; kicker?: ReactNode }) {
  return (
    <header className={styles.pageHead}>
      <div>
        {kicker && <div className={styles.kicker}>{kicker}</div>}
        <h1 className={styles.pageTitle}>{title}</h1>
        {lede && <p className={styles.pageLede}>{lede}</p>}
      </div>
      {actions && <div className={styles.pageActions}>{actions}</div>}
    </header>
  );
}

/** The sign-off stamp: drops onto the page once, when the tax advisor locks the month. */
export function Stamp({ show, label, sub }: { show: boolean; label: string; sub?: string }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className={styles.stamp}
          initial={{ opacity: 0, scale: 1.6, rotate: -14 }}
          animate={{ opacity: 1, scale: 1, rotate: -7 }}
          transition={m.spring}
          role="status"
        >
          <span className={styles.stampLabel}>{label}</span>
          {sub && <span className={styles.stampSub}>{sub}</span>}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className={styles.kbd}>{children}</kbd>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "ok"; children: ReactNode }) {
  return (
    <motion.div
      className={`${styles.notice} ${styles[tone]}`}
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: m.base, ease: m.ease }}
      role={tone === "warn" ? "alert" : "status"}
    >
      {children}
    </motion.div>
  );
}
