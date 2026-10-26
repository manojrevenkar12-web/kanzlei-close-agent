-- Tables. Money in cents (bigint). Periods as 'YYYY-MM'.

CREATE TABLE firms (
  id             text PRIMARY KEY,
  name           text NOT NULL,
  city           text NOT NULL DEFAULT '',
  chart          text NOT NULL CHECK (chart IN ('SKR03', 'SKR04')),
  berater_nr     int  NOT NULL,
  llm_agreement_on date,              -- § 62a StBerG agreement with the model provider, if any
  onboarded_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE staff (
  login    text PRIMARY KEY,
  firm_id  text REFERENCES firms,
  name     text NOT NULL,
  role     text NOT NULL CHECK (role IN ('buchhaltung', 'berater', 'gruppe')),
  CHECK ((role = 'gruppe') = (firm_id IS NULL))
);

CREATE TABLE clients (
  id              text PRIMARY KEY,
  firm_id         text NOT NULL REFERENCES firms,
  mandant_nr      int  NOT NULL,
  name            text NOT NULL,
  legal_form      text NOT NULL DEFAULT '',
  industry        text NOT NULL DEFAULT '',
  booking_method  text NOT NULL CHECK (booking_method IN ('direkt', 'opos')),
  vat_regime      text NOT NULL CHECK (vat_regime IN ('soll', 'ist', 'klein', 'befreit')),  -- befreit: tax-free sales without input VAT deduction (§ 4 Nr. 14, § 15 Abs. 2 UStG)
  vat_period      text NOT NULL CHECK (vat_period IN ('monat', 'quartal')),
  dauerfrist      boolean NOT NULL DEFAULT false,
  vat_id          text,
  own_ibans       text[] NOT NULL DEFAULT '{}',
  contact_name    text NOT NULL DEFAULT '',
  contact_email   text NOT NULL DEFAULT '',
  fiscal_year_start_month int NOT NULL DEFAULT 1,
  UNIQUE (firm_id, mandant_nr)
);

CREATE TABLE assignments (
  login     text REFERENCES staff ON DELETE CASCADE,
  client_id text REFERENCES clients ON DELETE CASCADE,
  PRIMARY KEY (login, client_id)
);

-- Accounts a firm's history uses beyond the standard chart. family NULL: not mapped yet.
CREATE TABLE firm_accounts (
  firm_id    text NOT NULL REFERENCES firms,
  account    int  NOT NULL,
  name       text NOT NULL DEFAULT '',
  family     text,
  role       text,
  tax        text NOT NULL DEFAULT '*',
  rows       int  NOT NULL DEFAULT 0,
  mapped_by  text,
  mapped_at  timestamptz,
  PRIMARY KEY (firm_id, account)
);

CREATE TABLE counterparties (
  id         bigserial PRIMARY KEY,
  client_id  text NOT NULL REFERENCES clients,
  kind       text NOT NULL CHECK (kind IN ('kreditor', 'debitor')),
  account    int  NOT NULL,
  name       text NOT NULL,
  norm_name  text NOT NULL,
  iban       text,
  vat_id     text,
  country    text,
  created_by text NOT NULL DEFAULT 'import',
  UNIQUE (client_id, account)
);
CREATE INDEX counterparties_iban ON counterparties (client_id, iban);

CREATE TABLE statements (
  id            bigserial PRIMARY KEY,
  client_id     text NOT NULL REFERENCES clients,
  iban          text NOT NULL,
  statement_id  text NOT NULL,
  sha256        text NOT NULL,
  from_date     date,
  to_date       date,
  opening_cents bigint NOT NULL,
  closing_cents bigint NOT NULL,
  imported_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id, sha256)
);

CREATE TABLE transactions (
  id                bigserial PRIMARY KEY,
  client_id         text NOT NULL REFERENCES clients,
  statement_id      bigint NOT NULL REFERENCES statements,
  seq               int NOT NULL,
  booking_date      date NOT NULL,
  value_date        date,
  amount_cents      bigint NOT NULL,
  counterparty_name text NOT NULL DEFAULT '',
  counterparty_iban text,
  remittance        text NOT NULL DEFAULT '',
  end_to_end_id     text,
  mandate_id        text,
  bank_code         text,
  period            text NOT NULL,
  UNIQUE (statement_id, seq)
);
CREATE INDEX transactions_period ON transactions (client_id, period);

CREATE TABLE documents (
  id          bigserial PRIMARY KEY,
  client_id   text NOT NULL REFERENCES clients,
  sha256      text NOT NULL,
  filename    text NOT NULL,
  media_type  text NOT NULL,
  storage_key text NOT NULL,
  source      text NOT NULL,            -- upload | portal | email | import
  format      text NOT NULL,            -- xrechnung-ubl | xrechnung-cii | zugferd | pdf
  direction   text NOT NULL CHECK (direction IN ('in', 'out')),
  invoice     jsonb NOT NULL,
  invoice_no  text,
  issue_date  date,
  seller_name text NOT NULL DEFAULT '',
  gross_cents bigint,
  period      text NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  superseded_by bigint REFERENCES documents,   -- a corrected invoice replaces this one
  UNIQUE (client_id, sha256)
);
CREATE INDEX documents_period ON documents (client_id, period);

CREATE TABLE closes (
  client_id     text NOT NULL REFERENCES clients,
  period        text NOT NULL,
  status        text NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'in_arbeit', 'freigabe', 'festgeschrieben')),
  last_run_at   timestamptz,
  run_summary   jsonb NOT NULL DEFAULT '{}',
  ustva         jsonb,
  flags         jsonb NOT NULL DEFAULT '[]',
  signed_by     text,
  signed_at     timestamptz,
  export_sha256 text,
  PRIMARY KEY (client_id, period)
);

CREATE TABLE items (
  id             bigserial PRIMARY KEY,
  client_id      text NOT NULL REFERENCES clients,
  period         text NOT NULL,
  kind           text NOT NULL CHECK (kind IN ('payment', 'invoice')),
  transaction_id bigint UNIQUE REFERENCES transactions,
  document_ids   bigint[] NOT NULL DEFAULT '{}',
  state          text NOT NULL CHECK (state IN ('auto', 'review', 'client', 'done', 'parked')),
  proposal       jsonb NOT NULL,
  final          jsonb,
  decision       text,                  -- auto | accepted | corrected | client | parked
  decided_by     text,
  decided_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX items_period ON items (client_id, period, state);
CREATE UNIQUE INDEX items_invoice_document ON items ((document_ids[1])) WHERE kind = 'invoice';

CREATE TABLE bookings (
  id           bigserial PRIMARY KEY,
  client_id    text NOT NULL REFERENCES clients,
  period       text NOT NULL,
  booking_date date NOT NULL,
  amount_cents bigint NOT NULL CHECK (amount_cents > 0),
  debit        int NOT NULL,
  credit       int NOT NULL,
  tax          text NOT NULL,
  text         text NOT NULL DEFAULT '',
  doc_ref      text NOT NULL DEFAULT '',
  family       text,
  role         text,
  item_id      bigint REFERENCES items,
  document_id  bigint REFERENCES documents,
  origin       text NOT NULL CHECK (origin IN ('import', 'auto', 'review', 'client', 'manual')),
  locked       boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bookings_period ON bookings (client_id, period);
CREATE INDEX bookings_item ON bookings (item_id);

CREATE TABLE queries (
  id          bigserial PRIMARY KEY,
  client_id   text NOT NULL REFERENCES clients,
  period      text NOT NULL,
  token_hash  text NOT NULL UNIQUE,
  status      text NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'beantwortet', 'geschlossen')),
  subject     text NOT NULL,
  message     text NOT NULL,
  sent_at     timestamptz NOT NULL DEFAULT now(),
  due_on      date NOT NULL,
  answered_at timestamptz
);
CREATE INDEX queries_period ON queries (client_id, period);

CREATE TABLE query_items (
  id          bigserial PRIMARY KEY,
  query_id    bigint NOT NULL REFERENCES queries ON DELETE CASCADE,
  client_id   text NOT NULL REFERENCES clients,
  item_id     bigint NOT NULL REFERENCES items,
  reason      text NOT NULL,
  question    text NOT NULL,
  options     jsonb NOT NULL,
  answer      jsonb,
  answered_at timestamptz,
  UNIQUE (query_id, item_id)
);

-- Staff corrections: the signal the group engineer iterates on.
CREATE TABLE corrections (
  id           bigserial PRIMARY KEY,
  firm_id      text NOT NULL REFERENCES firms,
  client_id    text NOT NULL REFERENCES clients,
  item_id      bigint NOT NULL REFERENCES items,
  login        text NOT NULL,
  from_family  text,
  to_family    text,
  from_tax     text,
  to_tax       text,
  reason       text NOT NULL DEFAULT '',
  at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE imports (
  id        bigserial PRIMARY KEY,
  firm_id   text NOT NULL REFERENCES firms,
  client_id text REFERENCES clients,
  kind      text NOT NULL,
  filename  text NOT NULL,
  sha256    text NOT NULL,
  rows      int NOT NULL,
  summary   jsonb NOT NULL DEFAULT '{}',
  at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (firm_id, sha256)
);

-- Protocol (GoBD: traceable, unchangeable). Each row hashes the previous one.
CREATE TABLE events (
  id        bigserial PRIMARY KEY,
  at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  actor     text NOT NULL,
  firm_id   text,
  client_id text,
  kind      text NOT NULL,
  payload   jsonb NOT NULL DEFAULT '{}',
  prev_hash text NOT NULL,
  hash      text NOT NULL
);

CREATE TABLE jobs (
  id         bigserial PRIMARY KEY,
  kind       text NOT NULL,
  payload    jsonb NOT NULL,
  status     text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
  attempts   int NOT NULL DEFAULT 0,
  run_after  timestamptz NOT NULL DEFAULT now(),
  locked_at  timestamptz,
  error      text,
  result     jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_ready ON jobs (status, run_after);

CREATE TABLE outbox (
  id         bigserial PRIMARY KEY,
  client_id  text NOT NULL REFERENCES clients,
  to_email   text NOT NULL,
  subject    text NOT NULL,
  body       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at    timestamptz
);

-- Festschreibung: a signed-off month cannot change. Corrections go into an open month.
CREATE FUNCTION forbid_locked_booking() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.locked THEN RAISE EXCEPTION 'Buchung % ist festgeschrieben', OLD.id USING ERRCODE = 'check_violation'; END IF;
    RETURN OLD;
  END IF;
  IF OLD.locked THEN RAISE EXCEPTION 'Buchung % ist festgeschrieben', OLD.id USING ERRCODE = 'check_violation'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bookings_locked BEFORE UPDATE OR DELETE ON bookings FOR EACH ROW EXECUTE FUNCTION forbid_locked_booking();

CREATE FUNCTION period_signed(cid text, per text) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT EXISTS (SELECT 1 FROM closes WHERE client_id = cid AND period = per AND status = 'festgeschrieben') $$;

CREATE FUNCTION forbid_closed_item() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF period_signed(OLD.client_id, OLD.period) THEN RAISE EXCEPTION 'Monat % ist festgeschrieben', OLD.period USING ERRCODE = 'check_violation'; END IF;
    RETURN OLD;
  END IF;
  IF period_signed(NEW.client_id, NEW.period) THEN RAISE EXCEPTION 'Monat % ist festgeschrieben', NEW.period USING ERRCODE = 'check_violation'; END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION forbid_closed_booking() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF period_signed(OLD.client_id, OLD.period) THEN RAISE EXCEPTION 'Monat % ist festgeschrieben', OLD.period USING ERRCODE = 'check_violation'; END IF;
    RETURN OLD;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.locked AND NOT OLD.locked THEN RETURN NEW; END IF;  -- the sign-off itself
  END IF;
  IF period_signed(NEW.client_id, NEW.period) THEN RAISE EXCEPTION 'Monat % ist festgeschrieben', NEW.period USING ERRCODE = 'check_violation'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bookings_closed BEFORE INSERT OR UPDATE OR DELETE ON bookings FOR EACH ROW EXECUTE FUNCTION forbid_closed_booking();
CREATE TRIGGER items_closed BEFORE INSERT OR UPDATE OR DELETE ON items FOR EACH ROW EXECUTE FUNCTION forbid_closed_item();

CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'check_violation'; END $$;
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events FOR EACH ROW EXECUTE FUNCTION forbid_change();
