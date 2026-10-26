const euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const plain = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat("de-DE", { style: "percent", maximumFractionDigits: 0 });

export const eur = (cents: number): string => euro.format(cents / 100);
export const amount = (cents: number): string => plain.format(cents / 100);
export const euros = (n: number): string => whole.format(n);
export const percent = (share: number): string => pct.format(share);

export function date(iso: string | null | undefined): string {
  if (!iso) return "–";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

const MONTHS = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

export function monthLabel(period: string): string {
  const [y = "", m = ""] = period.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
}

export function shortMonth(period: string): string {
  const [y = "", m = ""] = period.split("-");
  return `${(MONTHS[Number(m) - 1] ?? m).slice(0, 3)} ${y.slice(2)}`;
}

export function daysUntil(iso: string, today = new Date()): number {
  const target = new Date(`${iso}T00:00:00`);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target.getTime() - start.getTime()) / 86_400_000);
}

export const REGIME: Record<string, string> = {
  soll: "Soll-Versteuerung",
  ist: "Ist-Versteuerung",
  klein: "Kleinunternehmer",
  befreit: "Steuerfrei (§ 4 Nr. 14)",
};

export const METHOD: Record<string, string> = { direkt: "Direkt aus der Bank", opos: "Offene Posten" };

export const TAX_LABEL: Record<string, string> = {
  V19: "Vorsteuer 19 %",
  V7: "Vorsteuer 7 %",
  U19: "Umsatzsteuer 19 %",
  U7: "Umsatzsteuer 7 %",
  RC_EU19: "§ 13b EU-Leistung",
  RC_DRITT19: "§ 13b Drittland",
  RC_BAU19: "§ 13b Bauleistung",
  IGE19: "Innergem. Erwerb",
  IGL: "Innergem. Lieferung",
  EU_SVC: "EU-Leistung (§ 18b)",
  RC_OUT: "Steuerschuld Empfänger",
  FREI: "Steuerfrei",
  NONE: "ohne USt",
};
