import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { berater, board, periods } from "./fixtures";
import { clone, json, renderAt, signIn, stubApi } from "./harness";

describe("the month board", () => {
  beforeEach(() => signIn(berater));

  it("lists each client with what is booked, open and due", async () => {
    stubApi({ "GET /api/periods": periods, "GET /api/closes": board });
    renderAt("/abschluss");
    const link = await screen.findByRole("link", { name: /Elektro Baumann GmbH öffnen/ });
    expect(link).toHaveAttribute("href", "/mandanten/hp-10101/2026-09");
    const row = link.closest("li, tr, a") as HTMLElement;
    expect(within(row).getByText(/30 von 32 gebucht/)).toBeInTheDocument();
    expect(screen.getByText("keine Voranmeldung")).toBeInTheDocument();
  });

  it("switches month and asks the API for it", async () => {
    const calls = stubApi({ "GET /api/periods": periods, "GET /api/closes": board });
    renderAt("/abschluss");
    await userEvent.click(await screen.findByRole("tab", { name: "Aug 26" }));
    await screen.findByRole("tab", { name: "Aug 26", selected: true });
    expect(calls.some((c) => c.path === "/api/closes?period=2026-08")).toBe(true);
  });

  it("explains an empty firm instead of showing a blank page", async () => {
    stubApi({ "GET /api/periods": [], "GET /api/closes": [] });
    renderAt("/abschluss");
    expect(await screen.findByRole("heading", { name: "Noch keine Kontoauszüge" })).toBeInTheDocument();
  });

  it("shows a server error with a retry that recovers", async () => {
    let n = 0;
    stubApi({
      "GET /api/periods": periods,
      "GET /api/closes": () =>
        n++ === 0 ? json({ detail: "Datenbank nicht erreichbar" }, 503) : clone(board),
    });
    renderAt("/abschluss");
    expect(await screen.findByRole("alert")).toHaveTextContent("Datenbank nicht erreichbar");
    await userEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(await screen.findByRole("link", { name: /Elektro Baumann GmbH öffnen/ })).toBeInTheDocument();
  });
});
