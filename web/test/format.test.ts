import {
  amount,
  date,
  daysUntil,
  eur,
  euros,
  monthLabel,
  percent,
  shortMonth,
} from "../src/shared/lib/format";

describe("German number and date formats", () => {
  it("formats cents as amounts with comma and thousands dots", () => {
    expect(amount(-223450)).toBe("-2.234,50");
    expect(amount(5)).toBe("0,05");
    expect(eur(16675)).toMatch(/^166,75\s€$/);
  });

  it("rounds VAT bases to whole euros and shares to percent", () => {
    expect(euros(865)).toBe("865");
    expect(euros(12345)).toBe("12.345");
    expect(percent(0.938)).toMatch(/^94\s%$/);
  });

  it("writes dates and months the way a German form does", () => {
    expect(date("2026-11-10")).toBe("10.11.2026");
    expect(date("2026-11-10T08:00:00Z")).toBe("10.11.2026");
    expect(date(null)).toBe("–");
    expect(monthLabel("2026-03")).toBe("März 2026");
    expect(shortMonth("2026-09")).toBe("Sep 26");
  });

  it("counts days to a due date from the start of today", () => {
    expect(daysUntil("2026-11-10", new Date(2026, 9, 26, 23, 59))).toBe(15);
    expect(daysUntil("2026-10-25", new Date(2026, 9, 26))).toBe(-1);
  });
});
