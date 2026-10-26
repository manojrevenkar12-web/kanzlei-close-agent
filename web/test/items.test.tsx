import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ItemDetailResponse } from "../src/shared/api/types";
import { berater, C, families, itemAuto, itemClient, itemReview, items, PERIOD } from "./fixtures";
import { clone, json, renderAt, signIn, stubApi, type Routes } from "./harness";

const base = (over: Routes = {}): Routes => ({
  [`GET ${C}/${PERIOD}/items`]: items,
  [`GET /api/items/${itemClient.id}`]: itemClient,
  [`GET /api/items/${itemReview.id}`]: itemReview,
  [`GET /api/items/${itemAuto.id}`]: itemAuto,
  "GET /api/families": families,
  ...over,
});

const decided = (d: ItemDetailResponse, state: ItemDetailResponse["state"]) => ({
  ...clone(d),
  state,
  final_lines: d.proposal_lines,
  decided_by: "Claudia Hartmann",
});

describe("working through a client's month", () => {
  beforeEach(() => signIn(berater));

  it("opens on what is still open, with counts on every filter", async () => {
    stubApi(base());
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    expect(
      await screen.findByRole("heading", { name: "Elektro Baumann GmbH", level: 1 }),
    ).toBeInTheDocument();
    const filters = screen.getByRole("tablist", { name: "Filter" });
    expect(within(filters).getByRole("tab", { name: /Offen\s*2/ })).toHaveAttribute("aria-selected", "true");
    expect(within(filters).getByRole("tab", { name: /Automatisch gebucht\s*30/ })).toBeInTheDocument();
    // The first open item is shown in detail: the meal waiting for the client.
    expect(await screen.findByRole("heading", { name: "Café Ratskeller", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Rückfrage an den Mandanten")).toBeInTheDocument();
    // A meal still waiting on the client cannot be accepted blindly.
    expect(screen.queryByRole("button", { name: "Übernehmen" })).not.toBeInTheDocument();
  });

  it("explains why the agent proposed a booking", async () => {
    stubApi(base());
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await userEvent.click(await screen.findByRole("button", { name: /Werkzeugzentrum Reuter/ }));
    const detail = await screen.findByRole("heading", { name: "Werkzeugzentrum Reuter GmbH", level: 2 });
    const article = detail.closest("article") as HTMLElement;
    expect(within(article).getByText("Warum")).toBeInTheDocument();
    expect(within(article).getByText("Anlagegut über 800 € netto")).toBeInTheDocument();
    expect(within(article).getAllByRole("table")[0]).toHaveTextContent(/Soll/);
  });

  it("accepts a proposal under review and refreshes the list", async () => {
    let listCalls = 0;
    const calls = stubApi(
      base({
        [`GET ${C}/${PERIOD}/items`]: () => {
          listCalls++;
          return items;
        },
        [`POST /api/items/${itemReview.id}/accept`]: decided(itemReview, "done"),
      }),
    );
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await userEvent.click(await screen.findByRole("button", { name: /Werkzeugzentrum Reuter/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Übernehmen" }));
    expect(await screen.findByText(/Entschieden von Claudia Hartmann/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
      `/api/items/${itemReview.id}/accept`,
    ]);
    expect(listCalls).toBeGreaterThan(1);
  });

  it("corrects a proposal with a family, a tax code and a note for the team", async () => {
    const calls = stubApi(
      base({ [`POST /api/items/${itemReview.id}/correct`]: decided(itemReview, "done") }),
    );
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await userEvent.click(await screen.findByRole("button", { name: /Werkzeugzentrum Reuter/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Korrigieren" }));
    await userEvent.selectOptions(screen.getByLabelText("Was ist es?"), "goods");
    await userEvent.selectOptions(screen.getByLabelText("Steuer"), "V7");
    await userEvent.type(screen.getByLabelText(/Hinweis für das Team/), "Verbrauchsmaterial, kein Anlagegut");
    await userEvent.click(screen.getByRole("button", { name: "Korrigiert buchen" }));
    await screen.findByText(/Entschieden von/);
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      family: "goods",
      tax: "V7",
      reason: "Verbrauchsmaterial, kein Anlagegut",
    });
  });

  it("parks a payment the client will not explain", async () => {
    const calls = stubApi(base({ [`POST /api/items/${itemClient.id}/park`]: decided(itemClient, "parked") }));
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await userEvent.click(await screen.findByRole("button", { name: "Auf Klärungskonto" }));
    await screen.findByText(/Entschieden von/);
    expect(calls.find((c) => c.method === "POST")).toMatchObject({
      path: `/api/items/${itemClient.id}/park`,
      body: { note: "Klärung" },
    });
  });

  it("shows the API's refusal next to the decision", async () => {
    stubApi(
      base({
        [`POST /api/items/${itemReview.id}/accept`]: json({ detail: "Der Monat ist festgeschrieben." }, 409),
      }),
    );
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await userEvent.click(await screen.findByRole("button", { name: /Werkzeugzentrum Reuter/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Übernehmen" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Der Monat ist festgeschrieben.");
  });

  it("moves through the list with j and k, and accepts with a", async () => {
    const calls = stubApi(base({ [`POST /api/items/${itemReview.id}/accept`]: decided(itemReview, "done") }));
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await screen.findByRole("heading", { name: "Café Ratskeller", level: 2 });
    await userEvent.keyboard("j");
    expect(
      await screen.findByRole("heading", { name: "Werkzeugzentrum Reuter GmbH", level: 2 }),
    ).toBeInTheDocument();
    await userEvent.keyboard("a");
    await screen.findByText(/Entschieden von/);
    expect(calls.some((c) => c.path === `/api/items/${itemReview.id}/accept`)).toBe(true);
    await userEvent.keyboard("k");
    expect(await screen.findByRole("heading", { name: "Café Ratskeller", level: 2 })).toBeInTheDocument();
  });

  it("says so when nothing is open any more", async () => {
    const allDone = clone(items);
    allDone.items = allDone.items.filter((i) => i.state === "auto");
    stubApi(base({ [`GET ${C}/${PERIOD}/items`]: allDone }));
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    expect(await screen.findByRole("heading", { name: "Nichts mehr offen" })).toBeInTheDocument();
  });

  it("guides a new client to upload the statement first", async () => {
    const empty = { ...clone(items), items: [], status: "offen" };
    stubApi(base({ [`GET ${C}/${PERIOD}/items`]: empty }));
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    expect(await screen.findByRole("heading", { name: "Noch keine Posten" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kontoauszug (CAMT)" })).toBeInTheDocument();
  });

  it("runs the close and refreshes", async () => {
    const calls = stubApi(
      base({ [`POST ${C}/${PERIOD}/run`]: { items: 32, created: { payment: 0, invoice: 0 } } }),
    );
    renderAt(`/mandanten/hp-10101/${PERIOD}`);
    await userEvent.click(await screen.findByRole("button", { name: "Abschluss ausführen" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === `${C}/${PERIOD}/run`)).toBe(true));
  });
});
