import type { UseQueryResult } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Amount, Button, MonthSwitch, QueryState, Runway, StateBadge } from "../src/shared/ui";

const q = <T,>(over: Partial<UseQueryResult<T>>) =>
  ({
    isPending: false,
    isError: false,
    data: undefined,
    error: null,
    refetch: vi.fn(),
    ...over,
  }) as unknown as UseQueryResult<T>;

describe("QueryState", () => {
  const view = (query: UseQueryResult<string[]>) =>
    render(
      <QueryState query={query} skeleton={<p>lädt</p>} isEmpty={(d) => d.length === 0} empty={<p>leer</p>}>
        {(d) => <p>{d.join(",")}</p>}
      </QueryState>,
    );

  it("shows the skeleton while loading", () => {
    view(q({ isPending: true }));
    expect(screen.getByText("lädt")).toBeInTheDocument();
  });

  it("shows the error with a retry that refetches", async () => {
    const refetch = vi.fn();
    view(q({ isError: true, error: new Error("Datenbank nicht erreichbar"), refetch }));
    expect(screen.getByRole("alert")).toHaveTextContent("Datenbank nicht erreichbar");
    await userEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("shows the empty state, then the content", () => {
    const { rerender } = view(q({ data: [] }));
    expect(screen.getByText("leer")).toBeInTheDocument();
    rerender(
      <QueryState query={q({ data: ["a", "b"] })} skeleton={null}>
        {(d) => <p>{d.join(",")}</p>}
      </QueryState>,
    );
    expect(screen.getByText("a,b")).toBeInTheDocument();
  });
});

describe("small parts", () => {
  it("a busy button is disabled and says so", () => {
    render(<Button busy>Festschreiben</Button>);
    const b = screen.getByRole("button", { name: "Festschreiben" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
  });

  it("amounts carry the sign and a euro sign", () => {
    render(<Amount cents={-16675} />);
    expect(screen.getByText(/−166,75/)).toBeInTheDocument();
  });

  it("state badges use the team's words", () => {
    render(<StateBadge state="client" />);
    expect(screen.getByText("Beim Mandanten")).toBeInTheDocument();
  });

  it("the runway describes every state for screen readers", () => {
    render(<Runway label="Elektro Baumann" total={32} counts={{ auto: 30, review: 1, client: 1 }} />);
    const img = screen.getByRole("img");
    expect(img.getAttribute("aria-label")).toMatch(/30/);
    expect(img.getAttribute("aria-label")).toMatch(/Beim Mandanten/);
  });

  it("the month switch marks the chosen month and reports a new choice", async () => {
    const pick = vi.fn();
    render(<MonthSwitch months={["2026-09", "2026-08"]} value="2026-09" onChange={pick} />);
    expect(screen.getByRole("tab", { name: "Sep 26" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Aug 26" }));
    expect(pick).toHaveBeenCalledWith("2026-08");
  });

  it("the month switch is hidden with a single month", () => {
    const { container } = render(<MonthSwitch months={["2026-09"]} value="2026-09" onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
