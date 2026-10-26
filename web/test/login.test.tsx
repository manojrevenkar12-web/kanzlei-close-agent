import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { session } from "../src/shared/lib/session";
import { berater, board, demoUsers, gruppe, periods, rollout, rolloutPeriods } from "./fixtures";
import { json, renderAt, stubApi } from "./harness";

describe("signing in", () => {
  it("sends a person without a session to the sign-in page", async () => {
    stubApi({ "GET /api/demo-users": demoUsers });
    renderAt("/abschluss");
    expect(await screen.findByRole("heading", { name: "Monatsabschluss" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Claudia Hartmann/ })).toBeInTheDocument();
  });

  it("an advisor lands on the board of her firm", async () => {
    const calls = stubApi({
      "GET /api/demo-users": demoUsers,
      "POST /api/session": { token: "t1" },
      "GET /api/me": berater,
      "GET /api/periods": periods,
      "GET /api/closes": board,
    });
    renderAt("/anmelden");
    await userEvent.click(await screen.findByRole("button", { name: /Claudia Hartmann/ }));
    expect(await screen.findByRole("link", { name: /Elektro Baumann GmbH öffnen/ })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/session")?.body).toEqual({ login: "c.hartmann" });
    expect(session.get()?.user.role).toBe("berater");
  });

  it("the group engineer lands on the rollout, which has no client data", async () => {
    stubApi({
      "GET /api/demo-users": demoUsers,
      "POST /api/session": { token: "t2" },
      "GET /api/me": gruppe,
      "GET /api/rollout/periods": rolloutPeriods,
      "GET /api/rollout": rollout,
    });
    renderAt("/anmelden");
    await userEvent.click(await screen.findByRole("button", { name: /Lena Hoffmann/ }));
    expect(await screen.findByRole("heading", { name: "Rollout über die Kanzleien" })).toBeInTheDocument();
    expect(screen.queryByText(/Elektro Baumann/)).not.toBeInTheDocument();
  });

  it("shows why sign-in failed", async () => {
    stubApi({
      "GET /api/demo-users": demoUsers,
      "POST /api/session": json({ detail: "Unbekannte Person" }, 401),
    });
    renderAt("/anmelden");
    await userEvent.click(await screen.findByRole("button", { name: /Selin/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unbekannte Person");
  });
});
