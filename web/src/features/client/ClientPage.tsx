import { useRef } from "react";
import { NavLink, useParams } from "react-router-dom";

import { METHOD, monthLabel, REGIME } from "../../shared/lib/format";
import { Button, Notice, PageHead, QueryState, SkeletonRows } from "../../shared/ui";
import { useItems, useRun, useUpload } from "./api";
import styles from "./Client.module.css";
import { ItemsTab } from "./ItemsTab";
import { QueriesTab } from "./QueriesTab";
import { VatTab } from "./VatTab";

const STATUS: Record<string, string> = {
  offen: "nicht begonnen",
  in_arbeit: "in Arbeit",
  freigabe: "zur Freigabe",
  festgeschrieben: "festgeschrieben",
};

export default function ClientPage() {
  const { clientId = "", period = "", tab = "posten" } = useParams();
  const items = useItems(clientId, period);
  const run = useRun(clientId, period);
  const upload = useUpload(clientId, period);
  const statementInput = useRef<HTMLInputElement>(null);
  const docInput = useRef<HTMLInputElement>(null);
  const locked = items.data?.status === "festgeschrieben";
  const base = `/mandanten/${clientId}/${period}`;

  return (
    <>
      <QueryState query={items} skeleton={<SkeletonRows rows={3} label="Mandant wird geladen" />}>
        {(d) => (
          <PageHead
            kicker={`${monthLabel(period)}, Mandant ${d.client.mandant_nr}, ${d.chart}`}
            title={d.client.name}
            lede={`${METHOD[d.client.booking_method]}, ${REGIME[d.client.vat_regime]}, ${d.client.vat_period === "quartal" ? "vierteljährliche" : "monatliche"} Voranmeldung. Abschluss ${STATUS[d.status]}.`}
            actions={
              !locked && (
                <>
                  <input
                    ref={statementInput}
                    type="file"
                    accept=".xml"
                    hidden
                    onChange={(e) =>
                      e.target.files?.[0] && upload.mutate({ file: e.target.files[0], kind: "statement" })
                    }
                  />
                  <input
                    ref={docInput}
                    type="file"
                    accept=".xml,.pdf"
                    hidden
                    onChange={(e) =>
                      e.target.files?.[0] && upload.mutate({ file: e.target.files[0], kind: "document" })
                    }
                  />
                  <Button
                    size="small"
                    onClick={() => statementInput.current?.click()}
                    busy={upload.isPending && upload.variables?.kind === "statement"}
                  >
                    Kontoauszug (CAMT)
                  </Button>
                  <Button
                    size="small"
                    onClick={() => docInput.current?.click()}
                    busy={upload.isPending && upload.variables?.kind === "document"}
                  >
                    Beleg hochladen
                  </Button>
                  <Button size="small" variant="primary" onClick={() => run.mutate()} busy={run.isPending}>
                    Abschluss ausführen
                  </Button>
                </>
              )
            }
          />
        )}
      </QueryState>
      {upload.isError && <Notice tone="warn">{(upload.error as Error).message}</Notice>}
      {upload.isSuccess && (
        <Notice tone="ok">Datei übernommen. Mit „Abschluss ausführen“ wird sie zugeordnet.</Notice>
      )}
      {run.isError && <Notice tone="warn">{(run.error as Error).message}</Notice>}
      {run.isSuccess && (
        <Notice tone="ok">
          {run.data.created.payment + run.data.created.invoice} neue Posten verarbeitet.
          {run.data.query && ` ${run.data.query.items} Fragen an den Mandanten verschickt.`}
        </Notice>
      )}
      <nav className={styles.tabs} aria-label="Bereiche">
        <NavLink
          end
          to={base}
          className={({ isActive }) => (isActive || tab === "posten" ? styles.tabOn : styles.tab)}
        >
          Posten
        </NavLink>
        <NavLink
          to={`${base}/rueckfragen`}
          className={({ isActive }) => (isActive ? styles.tabOn : styles.tab)}
        >
          Rückfragen
        </NavLink>
        <NavLink
          to={`${base}/umsatzsteuer`}
          className={({ isActive }) => (isActive ? styles.tabOn : styles.tab)}
        >
          Umsatzsteuer und Freigabe
        </NavLink>
      </nav>
      {tab === "rueckfragen" ? (
        <QueriesTab clientId={clientId} period={period} />
      ) : tab === "umsatzsteuer" ? (
        <VatTab clientId={clientId} period={period} />
      ) : (
        <ItemsTab clientId={clientId} period={period} locked={locked} />
      )}
    </>
  );
}
