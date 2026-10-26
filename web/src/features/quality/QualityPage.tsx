import { useQuery } from "@tanstack/react-query";

import { api } from "../../shared/api/client";
import { percent } from "../../shared/lib/format";
import { EmptyState, PageHead, QueryState, SkeletonRows } from "../../shared/ui";
import styles from "./Quality.module.css";

type Metrics = Record<string, unknown> & {
  items: number;
  client_months: number;
  booked_automatically_share: number;
  automatic_wrong: number;
  automatic_wrong_share: number;
  no_staff_touch_share: number;
  first_proposal_right: number;
  review_proposal_right: number;
  client_questions: number;
  questions_needed_share: number;
  parked: number;
  vat_return_exact_months: number;
  signed_off_months: number;
  staff_minutes_estimate: number;
  manual_minutes_estimate: number;
  status?: string;
};

interface Evaluation {
  generated_at: string;
  sets: Record<string, Metrics>;
  first_runs: Record<string, Metrics>;
}

const ROWS: { key: keyof Metrics; label: string; fmt: (m: Metrics) => string }[] = [
  { key: "items", label: "Posten (Bankumsätze und Rechnungseingänge)", fmt: (m) => String(m.items) },
  { key: "booked_automatically_share", label: "Vom Agenten allein gebucht", fmt: (m) => percent(m.booked_automatically_share) },
  { key: "automatic_wrong", label: "Davon falsch", fmt: (m) => `${m.automatic_wrong} (${percent(m.automatic_wrong_share)})` },
  { key: "no_staff_touch_share", label: "Ohne Handgriff im Team (Agent oder Antwort des Mandanten)", fmt: (m) => percent(m.no_staff_touch_share) },
  { key: "first_proposal_right", label: "Erster Vorschlag richtig", fmt: (m) => percent(m.first_proposal_right) },
  { key: "review_proposal_right", label: "Vorschlag richtig, wo das Team geprüft hat", fmt: (m) => percent(m.review_proposal_right) },
  { key: "client_questions", label: "Fragen an Mandanten (davon nötig)", fmt: (m) => `${m.client_questions} (${percent(m.questions_needed_share)})` },
  { key: "parked", label: "Auf dem Klärungskonto (Mandant antwortet nicht)", fmt: (m) => String(m.parked) },
  { key: "vat_return_exact_months", label: "Voranmeldung auf den Cent wie die Wahrheit", fmt: (m) => `${m.vat_return_exact_months} von ${m.client_months} Monaten` },
  { key: "staff_minutes_estimate", label: "Geschätzte Teamminuten (von Hand: Schätzung)", fmt: (m) => `${Math.round(m.staff_minutes_estimate)} (${Math.round(m.manual_minutes_estimate)})` },
];

const NAMES: Record<string, string> = { dev: "Entwicklungsmonate" };

export default function QualityPage() {
  const ev = useQuery({ queryKey: ["evaluation"], queryFn: () => api.get<Evaluation>("/api/evaluation") });
  return (
    <>
      <PageHead
        title="Wie gut ist der Agent?"
        lede="Gemessen an simulierten Kanzleien, bei denen die richtige Buchung jedes Postens bekannt ist. Die Blindsätze hat jemand geschrieben, der den Code nie gesehen hat; ihr erster Lauf wird festgehalten und nicht überschrieben."
      />
      <QueryState query={ev} skeleton={<SkeletonRows rows={10} label="Auswertung wird geladen" />} isEmpty={(d) => Object.keys(d.sets).length === 0} empty={<EmptyState title="Noch keine Auswertung" />}>
        {(d) => {
          const cols = [
            ...Object.entries(d.first_runs).map(([k, v]) => ({ key: `${k}-first`, title: `${k}, erster Lauf`, m: v })),
            ...Object.entries(d.sets).map(([k, v]) => ({ key: k, title: NAMES[k] ?? `${k}, heute`, m: v })),
          ];
          return (
            <div className={styles.wrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Messgröße</th>
                    {cols.map((c) => (
                      <th key={c.key} scope="col" className={styles.num}>
                        {c.title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map((r) => (
                    <tr key={String(r.key)}>
                      <th scope="row">{r.label}</th>
                      {cols.map((c) => (
                        <td key={c.key} className={styles.num}>
                          {c.m[r.key] === undefined ? "–" : r.fmt(c.m)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={styles.note}>
                Stand {new Date(d.generated_at).toLocaleString("de-DE")}. Gemessen ohne Sprachmodell. Die Minuten sind eine Schätzung aus config/close.yaml, keine Messung.
              </p>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
