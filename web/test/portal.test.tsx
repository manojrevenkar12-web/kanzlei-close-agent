import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { portal } from "./fixtures";
import { clone, json, renderAt, stubApi } from "./harness";

const TOKEN = "tok";
const P = `/api/portal/${TOKEN}`;

describe("the client portal", () => {
  it("needs no sign-in and shows the open questions", async () => {
    stubApi({ [`GET ${P}`]: portal });
    renderAt(`/portal/${TOKEN}`);
    expect(
      await screen.findByRole("heading", { name: /Fragen zur Buchhaltung September 2026/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 Fragen sind offen/)).toBeInTheDocument();
  });

  it("asks for the purpose before a business answer can be sent", async () => {
    let answered = false;
    const calls = stubApi({
      [`GET ${P}`]: () => {
        const b = clone(portal);
        if (answered) b.items[1]!.answer = { choice: "business" };
        return b;
      },
      [`POST ${P}/items/599`]: () => {
        answered = true;
        return { ok: true };
      },
    });
    renderAt(`/portal/${TOKEN}`);
    const form = (await screen.findByText(/Frischemarkt Hansen/)).closest("form") as HTMLElement;
    const send = form.querySelector("button[type=submit]") as HTMLButtonElement;
    expect(send).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Betrieblich"));
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Wofür war das?"), "Getränke für das Büro");
    expect(send).toBeEnabled();
    await userEvent.click(send);
    expect(await screen.findByText("Beantwortet. Danke!")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      choice: "business",
      purpose: "Getränke für das Büro",
    });
  });

  it("uploads a receipt as a file", async () => {
    const calls = stubApi({ [`GET ${P}`]: portal, [`POST ${P}/items/588/upload`]: { ok: true } });
    renderAt(`/portal/${TOKEN}`);
    await userEvent.click(await screen.findByLabelText("Beleg hochladen"));
    const file = new File(["%PDF-1.4"], "tankbeleg.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/Beleg \(PDF oder E-Rechnung\)/), file);
    await userEvent.click(screen.getAllByRole("button", { name: "Antwort senden" })[0]!);
    await vi.waitFor(() => expect(calls.some((c) => c.path === `${P}/items/588/upload`)).toBe(true));
    const sent = calls.find((c) => c.path.endsWith("/upload"))?.body as Record<string, File>;
    expect(sent["file"]?.name).toBe("tankbeleg.pdf");
  });

  it("says plainly when a link has expired", async () => {
    stubApi({ [`GET ${P}`]: json({ detail: "Dieser Link ist abgelaufen." }, 404) });
    renderAt(`/portal/${TOKEN}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("Dieser Link ist abgelaufen.");
  });

  it("thanks the client when everything is answered", async () => {
    stubApi({ [`GET ${P}`]: { ...clone(portal), items: [] } });
    renderAt(`/portal/${TOKEN}`);
    expect(await screen.findByRole("heading", { name: "Keine offenen Fragen" })).toBeInTheDocument();
  });
});
