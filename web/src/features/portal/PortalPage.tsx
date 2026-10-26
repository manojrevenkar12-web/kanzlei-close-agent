import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../shared/api/client";
import type { PortalBundle, PortalOption } from "../../shared/api/types";
import { date, monthLabel } from "../../shared/lib/format";
import { motion as m } from "../../shared/theme/tokens";
import { Button, EmptyState, ErrorState, QueryState, SkeletonRows } from "../../shared/ui";
import styles from "./Portal.module.css";

const FIELD: Record<string, string> = {
  purpose: "Wofür war das?",
  occasion: "Anlass",
  participants: "Teilnehmer",
  invoice_no: "Rechnungsnummer",
  note: "Bitte kurz erklären",
};

export default function PortalPage() {
  const { token = "" } = useParams();
  const bundle = useQuery({ queryKey: ["portal", token], queryFn: () => api.get<PortalBundle>(`/api/portal/${token}`) });
  return (
    <main className={styles.page}>
      <QueryState
        query={bundle}
        skeleton={<SkeletonRows rows={4} label="Fragen werden geladen" />}
        isEmpty={(d) => d.items.length === 0}
        empty={<EmptyState title="Keine offenen Fragen">Danke, es ist alles beantwortet.</EmptyState>}
      >
        {(b) => <Bundle b={b} token={token} />}
      </QueryState>
    </main>
  );
}

function Bundle({ b, token }: { b: PortalBundle; token: string }) {
  const open = b.items.filter((i) => !i.answer).length;
  return (
    <>
      <header className={styles.head}>
        <p className={styles.firm}>{b.firm}</p>
        <h1 className={styles.title}>Fragen zur Buchhaltung {monthLabel(b.period)}</h1>
        <p className={styles.lede}>
          {b.client}: {open === 0 ? "Danke, alle Fragen sind beantwortet." : `${open} ${open === 1 ? "Frage ist" : "Fragen sind"} offen. Bitte bis ${date(b.due_on)} beantworten.`}
        </p>
      </header>
      <ol className={styles.list}>
        {b.items.map((i, n) => (
          <motion.li key={i.item_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: n * m.stagger, duration: m.base }}>
            <Question token={token} itemId={i.item_id} question={i.question} options={i.options} answered={!!i.answer} />
          </motion.li>
        ))}
      </ol>
    </>
  );
}

function Question({ token, itemId, question, options, answered }: { token: string; itemId: number; question: string; options: PortalOption[]; answered: boolean }) {
  const qc = useQueryClient();
  const [choice, setChoice] = useState<string>("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
  const selected = options.find((o) => o.value === choice);
  const send = useMutation({
    mutationFn: async () => {
      if (choice === "upload") {
        if (!file) throw new Error("Bitte eine Datei wählen");
        const form = new FormData();
        form.append("file", file);
        return api.upload(`/api/portal/${token}/items/${itemId}/upload`, form);
      }
      return api.post(`/api/portal/${token}/items/${itemId}`, { choice, ...fields });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["portal", token] }),
  });
  const needs = (selected?.needs ?? []).filter((n) => n !== "file");
  const ready = choice && needs.every((n) => (fields[n] ?? "").trim()) && (choice !== "upload" || file);

  if (answered) {
    return (
      <section className={styles.done} aria-label="Beantwortete Frage">
        <p>{question}</p>
        <p className={styles.ok}>Beantwortet. Danke!</p>
      </section>
    );
  }
  const name = `q-${itemId}`;
  return (
    <form
      className={styles.card}
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate();
      }}
    >
      <fieldset>
        <legend className={styles.question}>{question}</legend>
        <div className={styles.options}>
          {options.map((o) => (
            <label key={o.value} className={choice === o.value ? styles.optionOn : styles.option}>
              <input type="radio" name={name} value={o.value} checked={choice === o.value} onChange={() => setChoice(o.value)} />
              {o.label}
            </label>
          ))}
        </div>
        {choice === "upload" && (
          <label className={styles.field}>
            Beleg (PDF oder E-Rechnung)
            <input type="file" accept=".pdf,.xml,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
        )}
        {needs.map((n) => (
          <label key={n} className={styles.field}>
            {FIELD[n] ?? n}
            <input value={fields[n] ?? ""} onChange={(e) => setFields({ ...fields, [n]: e.target.value })} maxLength={300} required />
          </label>
        ))}
      </fieldset>
      {send.isError && <ErrorState error={send.error} title="Nicht gesendet" />}
      <Button type="submit" variant="primary" disabled={!ready} busy={send.isPending}>
        Antwort senden
      </Button>
    </form>
  );
}
