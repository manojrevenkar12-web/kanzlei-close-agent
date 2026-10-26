export type Role = "buchhaltung" | "berater" | "gruppe";

export interface User {
  login: string;
  name: string;
  role: Role;
  firm: { id: string; name: string; city: string; chart: string } | null;
  can_sign_off: boolean;
}

export interface DemoUser {
  login: string;
  name: string;
  role: Role;
  firm: string | null;
}

export type CloseStatus = "offen" | "in_arbeit" | "freigabe" | "festgeschrieben";

export interface BoardRow {
  id: string;
  name: string;
  mandant_nr: number;
  legal_form: string;
  industry: string;
  booking_method: "direkt" | "opos";
  vat_regime: "soll" | "ist" | "klein" | "befreit";
  vat_period: "monat" | "quartal";
  status: CloseStatus;
  items: number;
  auto: number;
  reviewed: number;
  by_client: number;
  open_review: number;
  open_client: number;
  parked: number;
  transactions: number;
  unprocessed: number;
  assigned: string | null;
  due_on: string;
  files_vat_this_month: boolean;
  signed_at: string | null;
}

export interface Flag {
  code: string;
  label: string;
  client: boolean;
}

export interface ItemSummary {
  id: number;
  kind: "payment" | "invoice";
  state: "auto" | "review" | "client" | "done" | "parked";
  decision: string | null;
  date: string | null;
  amount_cents: number;
  counterparty: string;
  remittance: string;
  family: string | null;
  family_label: string | null;
  tax: string | null;
  confidence: number;
  source: string | null;
  flags: Flag[];
  documents: number;
  accounts: string[];
}

export interface ItemsResponse {
  client: { id: string; name: string; mandant_nr: number; booking_method: string; vat_regime: string; vat_period: string; legal_form: string; industry: string };
  chart: string;
  status: CloseStatus;
  run_summary: Record<string, unknown> | null;
  items: ItemSummary[];
}

export interface LineView {
  date: string;
  amount_cents: number;
  debit: number;
  credit: number;
  tax: string;
  text: string;
  family: string | null;
  role: string | null;
  doc_ref: string;
  debit_label: string;
  credit_label: string;
  bu: string;
}

export interface InvoiceView {
  source: string;
  invoice_no: string | null;
  issue_date: string | null;
  delivery_from: string | null;
  seller: string;
  seller_vat_id: string | null;
  seller_country: string;
  buyer: string;
  lines: { description: string; net_cents: number; rate: number | null; category: string | null }[];
  taxes: { category: string; rate: number; base_cents: number; tax_cents: number }[];
  gross_cents: number | null;
  notes: string[];
  issues: string[];
}

export interface DocView {
  id: number;
  filename: string;
  format: string;
  direction: string;
  source: string;
  invoice: InvoiceView;
}

export interface ItemDetailResponse extends Omit<ItemSummary, "documents"> {
  client_id: string;
  period: string;
  chart: string;
  iban: string | null;
  proposal_lines: LineView[];
  final_lines: LineView[] | null;
  reasons: { code: string; text: string }[];
  documents: DocView[];
  questions: { reason: string; question: string; answer: Record<string, unknown> | null; status: string }[];
  history: { booking_date: string; amount_cents: number; tax: string; family: string; account: string }[];
  decided_by: string | null;
}

export interface Family {
  code: string;
  label: string;
  side: "expense" | "revenue" | "balance";
}

export interface QueryBundle {
  id: number;
  status: "offen" | "beantwortet" | "geschlossen";
  subject: string;
  message: string;
  sent_at: string;
  due_on: string;
  answered_at: string | null;
  items: { item_id: number; reason: string; reason_label: string; question: string; answer: Record<string, unknown> | null; state: string }[];
}

export interface UstvaRow {
  kz: string;
  label: string;
  base_cents: number;
  base_euros: number;
  tax_cents: number;
}

export interface Ustva {
  period: string;
  rows: UstvaRow[];
  flags: { kz: string; text: string }[];
  due_on: string;
  quarterly: boolean;
  files_this_month: boolean;
  history_months: number;
  kleinunternehmer: boolean;
  checks: { open_review: number; open_client: number; bank_reconciled: boolean; bank_difference_cents: number };
  close: { status: CloseStatus; signed_by?: string | null; signed_at?: string | null; export_sha256?: string | null };
  history: { period: string; kz81: number; kz66: number; kz83: number }[];
}

export interface PortalOption {
  value: string;
  label: string;
  needs?: string[];
}

export interface PortalBundle {
  client: string;
  firm: string;
  period: string;
  due_on: string;
  status: string;
  items: { item_id: number; reason: string; question: string; options: PortalOption[]; answer: Record<string, unknown> | null }[];
}

export interface RolloutFirm {
  firm_id: string;
  firm_name: string;
  chart: string;
  clients: number;
  items: number;
  auto: number;
  accepted: number;
  corrected: number;
  by_client: number;
  open_review: number;
  open_client: number;
  parked: number;
  signed_off: number;
  unmapped_accounts: number;
  automation_share: number;
  no_touch_share: number;
}

export interface Rollout {
  period: string;
  firms: RolloutFirm[];
  corrections: { firm_id: string; from_family: string | null; to_family: string | null; from_label: string | null; to_label: string | null; n: number }[];
  unmapped_accounts: { firm_id: string; account: number; name: string; rows: number }[];
}
