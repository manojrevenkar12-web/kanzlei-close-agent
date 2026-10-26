import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../../shared/api/client";
import type { Rollout, RolloutFirm } from "../../shared/api/types";
import { monthLabel, percent } from "../../shared/lib/format";
import {
  Button,
  EmptyState,
  ErrorState,
  MonthSwitch,
  PageHead,
  QueryState,
  Runway,
  SkeletonRows,
} from "../../shared/ui";
import { useFamilies } from "../client/api";
import styles from "./Rollout.module.css";

export default function RolloutPage() {
  const periods = useQuery({
    queryKey: ["rollout-periods"],
    queryFn: () => api.get<string[]>("/api/rollout/periods"),
  });
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? periods.data?.[0];
  const rollout = useQuery({
    queryKey: ["rollout", period],
    queryFn: () => api.get<Rollout>(`/api/rollout?period=${period}`),
    enabled: !!period,
  });
  return (
    <>
      <PageHead
        title="Rollout über die Kanzleien"
        kicker={period ? monthLabel(period) : undefined}
        lede="Wie weit der Agent in jeder Kanzlei der Gruppe trägt, wo Mitarbeiter ihn korrigieren und welche Konten aus übernommenen Kanzleien noch keiner Buchungsfamilie zugeordnet sind. Hier stehen nur Zahlen je Kanzlei, keine Mandantendaten."
        actions={
          <MonthSwitch
            months={periods.data ?? []}
            value={period}
            onChange={(p) => setParams({ period: p })}
          />
        }
      />
      <QueryState
        query={periods}
        skeleton={<SkeletonRows label="Monate werden geladen" />}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="Noch keine Monate in Arbeit" />}
      >
        {() => (
          <QueryState
            query={rollout}
            skeleton={<SkeletonRows rows={6} label="Kanzleien werden geladen" />}
            isEmpty={(d) => d.firms.length === 0}
            empty={<EmptyState title="Keine Kanzleien" />}
          >
            {(r) => <RolloutView r={r} />}
          </QueryState>
        )}
      </QueryState>
    </>
  );
}

function RolloutView({ r }: { r: Rollout }) {
  return (
    <div className={styles.grid}>
      <section className={styles.panel} aria-label="Kanzleien">
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Kanzlei</th>
              <th scope="col">Stand</th>
              <th scope="col" className={styles.num}>
                Automatisch
              </th>
              <th scope="col" className={styles.num}>
                Ohne Handgriff
              </th>
              <th scope="col" className={styles.num}>
                Korrigiert
              </th>
              <th scope="col" className={styles.num}>
                Festgeschrieben
              </th>
            </tr>
          </thead>
          <tbody>
            {r.firms.map((f) => (
              <Firm key={f.firm_id} f={f} />
            ))}
          </tbody>
        </table>
      </section>
      <section className={styles.panel} aria-labelledby="korr">
        <h2 id="korr" className={styles.h2}>
          Was Mitarbeiter korrigieren
        </h2>
        <p className={styles.small}>
          Die letzten 90 Tage: wo der Vorschlag falsch war. Daraus entstehen neue Regeln, Lexikon-Einträge
          oder Kontenzuordnungen.
        </p>
        {r.corrections.length === 0 ? (
          <p className={styles.small}>Noch keine Korrekturen.</p>
        ) : (
          <ol className={styles.corrections}>
            {r.corrections.map((c, i) => (
              <li key={i}>
                <span className={styles.n}>{c.n}×</span> {c.from_label ?? "kein Vorschlag"}{" "}
                <span aria-hidden>→</span>
                <span className="visually-hidden">korrigiert zu</span>{" "}
                <strong>{c.to_label ?? "manuell"}</strong> <span className={styles.small}>({c.firm_id})</span>
              </li>
            ))}
          </ol>
        )}
      </section>
      <Unmapped r={r} />
    </div>
  );
}

function Firm({ f }: { f: RolloutFirm }) {
  const reviewed = f.accepted + f.corrected;
  return (
    <tr>
      <th scope="row">
        <span className={styles.firm}>{f.firm_name}</span>
        <span className={styles.small}>
          {f.chart}, {f.clients} Mandanten, {f.items} Posten
        </span>
      </th>
      <td className={styles.runwayCell} data-label="Stand">
        <Runway
          label={f.firm_name}
          total={f.items}
          counts={{
            auto: f.auto,
            done: reviewed + f.by_client,
            client: f.open_client,
            review: f.open_review,
            parked: f.parked,
          }}
        />
      </td>
      <td className={styles.num} data-label="Automatisch">
        {percent(f.automation_share)}
      </td>
      <td className={styles.num} data-label="Ohne Handgriff">
        {percent(f.no_touch_share)}
      </td>
      <td className={styles.num} data-label="Korrigiert">
        {reviewed ? percent(f.corrected / reviewed) : "–"}
      </td>
      <td className={styles.num} data-label="Festgeschrieben">
        {f.signed_off} / {f.clients}
      </td>
    </tr>
  );
}

function Unmapped({ r }: { r: Rollout }) {
  const families = useFamilies();
  const qc = useQueryClient();
  const [choice, setChoice] = useState<Record<string, string>>({});
  const map = useMutation({
    mutationFn: ({ firm, account, family }: { firm: string; account: number; family: string }) =>
      api.put(`/api/firms/${firm}/accounts/${account}`, { family }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["rollout"] }),
  });
  return (
    <section className={styles.panel} aria-labelledby="konten">
      <h2 id="konten" className={styles.h2}>
        Konten ohne Zuordnung
      </h2>
      <p className={styles.small}>
        Konten aus der DATEV-Historie übernommener Kanzleien, die der Standard-Kontenrahmen nicht kennt. Erst
        zugeordnet lernt der Agent aus ihnen.
      </p>
      {r.unmapped_accounts.length === 0 ? (
        <p className={styles.small}>Alle Konten sind zugeordnet.</p>
      ) : (
        <ul className={styles.accounts}>
          {r.unmapped_accounts.map((a) => {
            const key = `${a.firm_id}:${a.account}`;
            return (
              <li key={key}>
                <span>
                  <strong>{a.account}</strong>{" "}
                  <span className={styles.small}>
                    {a.firm_id}, {a.rows} Buchungen
                  </span>
                </span>
                <select
                  aria-label={`Buchungsfamilie für Konto ${a.account}`}
                  value={choice[key] ?? ""}
                  onChange={(e) => setChoice({ ...choice, [key]: e.target.value })}
                >
                  <option value="">Familie wählen</option>
                  {(families.data ?? []).map((f) => (
                    <option key={f.code} value={f.code}>
                      {f.label}
                    </option>
                  ))}
                </select>
                <Button
                  size="small"
                  disabled={!choice[key]}
                  busy={map.isPending && map.variables?.account === a.account}
                  onClick={() =>
                    map.mutate({ firm: a.firm_id, account: a.account, family: choice[key] ?? "" })
                  }
                >
                  Zuordnen
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {map.isError && <ErrorState error={map.error} />}
    </section>
  );
}
