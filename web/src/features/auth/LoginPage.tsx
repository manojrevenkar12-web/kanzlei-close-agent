import { motion } from "framer-motion";
import { useLocation, useNavigate } from "react-router-dom";

import { Button, ErrorState, QueryState, SkeletonRows } from "../../shared/ui";
import { motion as m } from "../../shared/theme/tokens";
import type { DemoUser } from "../../shared/api/types";
import { useDemoUsers, useSignIn, useSignInMode } from "./api";
import styles from "./LoginPage.module.css";

const ROLE: Record<string, string> = {
  berater: "Steuerberatung: prüft und schreibt fest",
  buchhaltung: "Buchhaltung: bearbeitet die eigenen Mandanten",
  gruppe: "Gruppen-Team: Rollout über alle Kanzleien, keine Mandantendaten",
};

export default function LoginPage() {
  const mode = useSignInMode();
  const users = useDemoUsers(mode.data?.mode === "demo");
  const signIn = useSignIn();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;

  const go = (login: string | null) =>
    signIn.mutate(login, {
      onSuccess: (u) =>
        nav(from && from !== "/anmelden" ? from : u.role === "gruppe" ? "/gruppe" : "/abschluss", {
          replace: true,
        }),
    });

  return (
    <main className={styles.page}>
      <motion.section
        className={styles.sheet}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: m.slow, ease: m.ease }}
      >
        <h1 className={styles.title}>Monatsabschluss</h1>
        {signIn.isError && <ErrorState error={signIn.error} title="Anmeldung fehlgeschlagen" />}
        <QueryState query={mode} skeleton={<SkeletonRows rows={3} label="Anmeldung wird vorbereitet" />}>
          {({ mode: kind }) =>
            kind === "sso" ? (
              <>
                <p className={styles.lede}>
                  Bankumsätze und E-Rechnungen rein, geprüfte Buchungen, Umsatzsteuer-Voranmeldung und
                  DATEV-Export raus. Sie sind mit dem Konto Ihrer Kanzlei angemeldet.
                </p>
                <div>
                  <Button variant="primary" onClick={() => go(null)} busy={signIn.isPending}>
                    Weiter zum Monatsabschluss
                  </Button>
                </div>
              </>
            ) : kind === "demo" ? (
              <>
                <p className={styles.lede}>
                  Bankumsätze und E-Rechnungen rein, geprüfte Buchungen, Umsatzsteuer-Voranmeldung und
                  DATEV-Export raus. Demo-Zugang: wählen Sie eine Person.
                </p>
                <QueryState
                  query={users}
                  skeleton={<SkeletonRows rows={5} label="Personen werden geladen" />}
                  isEmpty={(d) => d.length === 0}
                  empty={
                    <p>Keine Demo-Personen angelegt. Bitte erst `python -m kanzlei_sim seed` ausführen.</p>
                  }
                >
                  {(list) => (
                    <People
                      list={list}
                      onPick={go}
                      busy={signIn.isPending ? (signIn.variables ?? "") : undefined}
                    />
                  )}
                </QueryState>
              </>
            ) : (
              <p className={styles.lede}>
                Für diese Installation ist keine Anmeldung eingerichtet. Der Betrieb verbindet sie mit dem
                Identity Provider der Gruppe (KANZLEI_ALB_ARN).
              </p>
            )
          }
        </QueryState>
      </motion.section>
    </main>
  );
}

function People({
  list,
  onPick,
  busy,
}: {
  list: DemoUser[];
  onPick: (login: string) => void;
  busy?: string;
}) {
  const groups = new Map<string, DemoUser[]>();
  for (const u of list) {
    const k = u.firm ?? "Gruppe";
    groups.set(k, [...(groups.get(k) ?? []), u]);
  }
  return (
    <div className={styles.groups}>
      {[...groups.entries()].map(([firm, people]) => (
        <section key={firm} aria-labelledby={`firm-${firm}`}>
          <h2 id={`firm-${firm}`} className={styles.firm}>
            {firm}
          </h2>
          <ul className={styles.people}>
            {people.map((p) => (
              <li key={p.login}>
                <button
                  type="button"
                  className={styles.person}
                  onClick={() => onPick(p.login)}
                  disabled={busy !== undefined}
                  aria-busy={busy === p.login || undefined}
                >
                  <span className={styles.name}>{p.name}</span>
                  <span className={styles.role}>{ROLE[p.role]}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
