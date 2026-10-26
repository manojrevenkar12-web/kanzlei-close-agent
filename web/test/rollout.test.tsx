import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { evaluation, families, gruppe, rollout, rolloutPeriods } from "./fixtures";
import { clone, renderAt, signIn, stubApi } from "./harness";

describe("the group's rollout view", () => {
  beforeEach(() => signIn(gruppe));

  it("compares firms by numbers only", async () => {
    stubApi({
      "GET /api/rollout/periods": rolloutPeriods,
      "GET /api/rollout": rollout,
      "GET /api/families": families,
    });
    renderAt("/gruppe");
    expect(await screen.findByRole("rowheader", { name: /Steuerbüro Brandt/ })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(rollout.firms.length + 1);
    expect(screen.getByText("Alle Konten sind zugeordnet.")).toBeInTheDocument();
  });

  it("maps an account from an acquired firm's DATEV history to a booking family", async () => {
    const r = clone(rollout);
    r.unmapped_accounts = [{ firm_id: "brandt", account: 4985, name: "Werkzeuge Altbestand", rows: 14 }];
    const calls = stubApi({
      "GET /api/rollout/periods": rolloutPeriods,
      "GET /api/rollout": r,
      "GET /api/families": families,
      "PUT /api/firms/brandt/accounts/4985": { ok: true },
    });
    renderAt("/gruppe");
    const select = await screen.findByLabelText("Buchungsfamilie für Konto 4985");
    await screen.findByRole("option", { name: "Wareneinkauf" });
    await userEvent.selectOptions(select, "goods");
    await userEvent.click(screen.getByRole("button", { name: "Zuordnen" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")).toMatchObject({ body: { family: "goods" } }),
    );
  });

  it("shows each blind set's first run beside today's run", async () => {
    stubApi({ "GET /api/evaluation": evaluation });
    renderAt("/qualitaet");
    const headers = (await screen.findAllByRole("columnheader")).map((h) => h.textContent);
    expect(headers.slice(0, 4)).toEqual(["Messgröße", "Entwicklungsmonate", "v1, erster Lauf", "v1, heute"]);
  });
});
