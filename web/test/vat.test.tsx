import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { berater, buchhaltung, C, items, PERIOD, ustvaOpen, ustvaSigned } from "./fixtures";
import { clone, renderAt, signIn, stubApi } from "./harness";

const ready = () => {
  const u = clone(ustvaOpen);
  u.checks = { ...u.checks, open_review: 0, open_client: 0, bank_reconciled: true, bank_difference_cents: 0 };
  return u;
};

describe("VAT return and sign-off", () => {
  it("lists the Kennzahlen with Kz 83 as the total", async () => {
    signIn(berater);
    stubApi({ [`GET ${C}/${PERIOD}/items`]: items, [`GET ${C}/${PERIOD}/ustva`]: ustvaOpen });
    renderAt(`/mandanten/hp-10101/${PERIOD}/umsatzsteuer`);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("81")).toBeInTheDocument();
    expect(within(table).getByText("Überschuss (Erstattung)")).toBeInTheDocument();
    expect(within(table).getByText("-1.866,47")).toBeInTheDocument();
  });

  it("will not sign off while items are open or the bank does not reconcile", async () => {
    signIn(berater);
    stubApi({ [`GET ${C}/${PERIOD}/items`]: items, [`GET ${C}/${PERIOD}/ustva`]: ustvaOpen });
    renderAt(`/mandanten/hp-10101/${PERIOD}/umsatzsteuer`);
    expect(await screen.findByRole("button", { name: "Monat festschreiben" })).toBeDisabled();
    expect(screen.getByText(/2 Posten offen/)).toBeInTheDocument();
    expect(screen.getByText(/166,75 € stecken in offenen Posten/)).toBeInTheDocument();
  });

  it("asks the advisor to confirm unusual figures before signing off", async () => {
    signIn(berater);
    const u = ready();
    u.flags = [{ kz: "66", text: "Vorsteuer dreimal so hoch wie im Durchschnitt der Vormonate" }];
    const calls = stubApi({
      [`GET ${C}/${PERIOD}/items`]: items,
      [`GET ${C}/${PERIOD}/ustva`]: u,
      [`POST ${C}/${PERIOD}/sign-off`]: { sha256: "ab".repeat(32), export: "EXTF.csv" },
    });
    renderAt(`/mandanten/hp-10101/${PERIOD}/umsatzsteuer`);
    const sign = await screen.findByRole("button", { name: "Monat festschreiben" });
    expect(sign).toBeDisabled();
    expect(screen.getByText(/dreimal so hoch/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Auffälligkeiten geprüft"));
    expect(sign).toBeEnabled();
    await userEvent.click(sign);
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ acknowledge_flags: true }),
    );
  });

  it("only the advisor signs off", async () => {
    signIn(buchhaltung);
    stubApi({ [`GET ${C}/${PERIOD}/items`]: items, [`GET ${C}/${PERIOD}/ustva`]: ready() });
    renderAt(`/mandanten/hp-10101/${PERIOD}/umsatzsteuer`);
    expect(await screen.findByText("Festgeschrieben wird von der Steuerberatung.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Monat festschreiben" })).not.toBeInTheDocument();
  });

  it("a signed month shows the stamp and offers the DATEV export", async () => {
    signIn(berater);
    const signedItems = { ...clone(items), status: "festgeschrieben" };
    stubApi({
      [`GET ${C}/2026-08/items`]: signedItems,
      [`GET ${C}/2026-08/ustva`]: ustvaSigned,
    });
    renderAt(`/mandanten/hp-10101/2026-08/umsatzsteuer`);
    expect(await screen.findByRole("button", { name: "DATEV-Export (EXTF)" })).toBeEnabled();
    expect(screen.getAllByText("Festgeschrieben").length).toBeGreaterThan(0);
    // No uploads or runs on a locked month.
    expect(screen.queryByRole("button", { name: "Abschluss ausführen" })).not.toBeInTheDocument();
  });
});
