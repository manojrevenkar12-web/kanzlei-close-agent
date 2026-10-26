import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { session, useSession } from "../shared/lib/session";
import styles from "./Layout.module.css";

const ROLE: Record<string, string> = { buchhaltung: "Buchhaltung", berater: "Steuerberatung", gruppe: "Gruppe" };

export function Layout() {
  const s = useSession();
  const qc = useQueryClient();
  const role = s?.user.role;
  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#inhalt">
        Zum Inhalt
      </a>
      <header className={styles.top}>
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden />
          <span>
            <strong>Monatsabschluss</strong>
            <span className={styles.firm}>{s?.user.firm?.name ?? "Gruppe"}</span>
          </span>
        </div>
        <nav className={styles.nav} aria-label="Hauptnavigation">
          {role !== "gruppe" && (
            <NavLink to="/abschluss" className={({ isActive }) => (isActive ? styles.active : undefined)}>
              Abschluss
            </NavLink>
          )}
          {(role === "gruppe" || role === "berater") && (
            <NavLink to="/gruppe" className={({ isActive }) => (isActive ? styles.active : undefined)}>
              Rollout
            </NavLink>
          )}
          <NavLink to="/qualitaet" className={({ isActive }) => (isActive ? styles.active : undefined)}>
            Qualität
          </NavLink>
        </nav>
        <div className={styles.user}>
          <span className={styles.userName}>{s?.user.name}</span>
          <span className={styles.userRole}>{role ? ROLE[role] : ""}</span>
          <button
            type="button"
            className={styles.logout}
            onClick={() => {
              session.clear();
              qc.clear();
            }}
          >
            Abmelden
          </button>
        </div>
      </header>
      <main id="inhalt" className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
