# Writing a blind set

You are writing test material for a system that closes the month for the clients of a German tax
firm (Steuerkanzlei). You must **not** look at the system's code. Read only this file. Your
files are run once through the system; that first run is recorded and published as is.

Write like a careful Steuerfachangestellte who knows the clients: invent realistic small German
businesses, their suppliers and customers, one month of their bank account, the receipts that
come with it, and for every payment the booking that is correct. Make it varied and honest. Do
not make it easy, and do not make it absurd: the kind of month a real firm sees.

## What to write

Two YAML files in this directory's set folder (for example `v1/firm_a.yaml`, `v1/firm_b.yaml`):

- one firm on the chart of accounts `SKR03`, one on `SKR04` (you never write account numbers;
  you write booking families and tax codes, below);
- per firm two or three clients of different kinds (a craft business, a freelancer, a retailer,
  an agency, a medical practice, a small manufacturer, an online shop, ...). Use every booking
  method and VAT regime at least once across both files;
- per client: its business partners, how it booked in the past months (`history`), and **one
  month** of events: `2026-09`. 30 to 45 events per client.

Invent every name. No real companies or people. Emails end in `.example`.

Validate as you go (this checks the form, not your judgement):

    cd backend && .venv/bin/python -m kanzlei_sim validate src/kanzlei_sim/blind/v1/*.yaml

## The file

```yaml
firm: {id: kanzlei-x, name: "...", city: "...", chart: SKR03, berater_nr: 12345}
staff:
  - {login: a.name, name: "...", role: berater}       # one tax advisor (signs off)
  - {login: b.name, name: "...", role: buchhaltung}   # one or two accountants
clients:
  - id: x-1001                 # unique across both files
    mandant_nr: 1001
    name: "..."
    legal_form: GmbH
    industry: "..."
    booking_method: direkt     # direkt: booked from the bank; opos: invoices booked on receipt
    vat_regime: ist            # soll | ist | klein (Kleinunternehmer § 19) | befreit (tax-free, e.g. medical, no input VAT)
    vat_period: monat          # monat | quartal
    iban: auto
    vat_id: auto               # or null for a Kleinunternehmer
    contact_name: "..."
    contact_email: "...@....example"
    assigned: [b.name]
    parties:
      - {key: strom, name: "...", role: supplier, iban: auto, vat_id: auto, country: DE, street: "...", postcode: "12345", city: "..."}
      - {key: kunde1, name: "...", role: customer, iban: auto, vat_id: auto, country: AT}
      - {key: tanke, name: "...", role: supplier, iban: null}      # card payments: no IBAN
      - {key: inhaber, name: "...", role: other, iban: auto}       # the owner's private account, the tax office, a health insurer, staff
    history:                   # monthly bookings before 2026-09; the system learns from these
      - {party: strom, family: utilities, tax: V19, amount: -238.00, months: 12}
      - {party: miete, family: rent, tax: NONE, amount: -1450.00, months: 12}
      - {party: kunde1, family: revenue, tax: IGL, amount: 3200.00, months: 8, vary: 0.4}
    months:
      "2026-09":
        - id: e01
          party: strom
          on: 2026-09-15
          method: lastschrift      # ueberweisung | lastschrift | karte | gutschrift (money in)
          reference: "Abschlag September Vertragskonto 4402211"
          document:
            format: zugferd        # xrechnung-ubl | xrechnung-cii | zugferd | pdf | none
            number: "R-2026-09-0815"
            issue_date: 2026-09-05
            delivery_date: 2026-09-01
            lines:
              - {text: "Abschlag Strom September", net: 200.00, rate: 19, category: S}
          truth: {family: utilities, tax: V19}
```

- `amount`: leave it out when there is a document; it is computed from the lines (negative for
  money out). Without a document, give it, signed (`-49.90` out, `1200.00` in).
- `history.amount` is the gross per booking as the bank saw it, signed. `vary` spreads it
  (0.2 = ±20 %). `months` up to 12, `per_month` for several per month.
- Event ids are unique per client. `on` is the bank date, inside 2026-09.

### Documents

- `format`: e-invoices (`xrechnung-ubl`, `xrechnung-cii`), `zugferd` (PDF with the XML inside),
  `pdf` (a plain PDF invoice or till receipt), `none` (no paper at all).
- `lines`: `net` in euros per line, `rate` 19 or 7 for category `S`, and the category:
  `S` standard, `AE` reverse charge (§ 13b), `K` intra-EU supply of goods, `E` exempt, `Z` zero
  rated, `O` outside the scope of German VAT (e.g. a US software vendor). Put `rate: 0` for all
  but `S`. Several lines with different rates are fine (a hotel: room 7 %, breakfast 19 %).
- `direction`: `in` (received by the client, default) or `out` (an invoice the client issued).
- `arrives`: `with_statement` (default: the client sent it with the month), `on_request` (only
  when the firm asks), `never` (lost).
- `missing`: leave out mandatory invoice details on purpose: `seller_name`, `seller_address`,
  `buyer_name`, `seller_tax_id`, `invoice_no`, `delivery_date`, `buyer_vat_id`.
- `notes`: free text printed on the invoice, e.g. `"Steuerschuldnerschaft des Leistungsempfängers"`,
  or on a restaurant bill `"Anlass: ...; Teilnehmer: ..."`.
- `payment_terms`: e.g. `"2 % Skonto bei Zahlung innerhalb von 10 Tagen"`.

### OPOS clients (booking_method: opos)

Invoices are booked when they arrive, against the supplier's or customer's personal account, and
the payment later settles them:

```yaml
        - id: r07
          kind: invoice
          party: grosshandel
          document: {format: zugferd, number: "...", issue_date: 2026-09-03, delivery_date: 2026-09-02, lines: [...]}
          truth: {family: goods, tax: V19}
        - id: z07
          party: grosshandel
          on: 2026-09-12
          settles: [r07]
          skonto: true            # paid less 2 %
          reference: "RE ... abzgl. 2 % Skonto"
          truth: {family: clearing}
```

Settled invoices must be in the same file. Direct debits for rent, energy, phone and similar are
usually booked straight from the bank, even at OPOS clients: write them as payments with a
document and the expense family. Give the partners of `kind: invoice` events an IBAN.

## The truth: family and tax code

For every event, `truth.family` says what it is, `truth.tax` how it is taxed. The system turns
these into SKR03/SKR04 accounts; you never write account numbers. Leave `tax` out when the
document's lines decide it (different rates on one invoice).

Families: `goods` (purchases for resale or material), `subcontractor`, `rent`, `utilities`,
`telecom`, `office_supplies`, `software`, `meals` (business entertainment, Bewirtung), `travel_lodging`,
`travel_transport`, `fuel`, `vehicle_repair`, `vehicle_leasing`, `vehicle_insurance`, `insurance`,
`memberships`, `advertising`, `advice` (tax advisor, lawyer), `bank_fees`, `postage`, `training`,
`repairs`, `equipment` (tools, devices, furniture), `payroll` (net salaries to staff),
`social_security` (to health insurers), `wage_tax`, `vat_payment` (to the tax office),
`private_withdrawal`, `private_deposit`, `transfer` (between the client's own accounts),
`revenue`, and `clearing` (only for a payment that settles OPOS invoices).

Tax codes:

| code | meaning |
| --- | --- |
| `V19`, `V7` | input VAT 19 % / 7 % from a proper German invoice |
| `U19`, `U7` | output VAT on the client's sales |
| `RC_EU19` | services from a business in another EU country (reverse charge, § 13b Abs. 1) |
| `RC_DRITT19` | services from a business outside the EU (§ 13b Abs. 2 Nr. 1) |
| `RC_BAU19` | construction services from a German subcontractor under § 13b |
| `IGE19` | goods bought from another EU country (intra-EU acquisition) |
| `IGL` | goods sold to a business in another EU country (tax-free) |
| `EU_SVC` | services sold to a business in another EU country |
| `RC_OUT` | services the client sold where the customer owes the VAT (§ 13b, e.g. construction) |
| `FREI` | tax-free sales without input VAT (e.g. medical) |
| `NONE` | no VAT: wages, insurance, fees, private, taxes, and everything at a Kleinunternehmer |

Rules a good bookkeeper follows, and which the truth must follow:

- No proper invoice, no input VAT. A purchase whose receipt never comes (`arrives: never`) is
  booked with `NONE`. An invoice that lacks mandatory details is only deducted once a corrected one
  arrives; if the client cannot get one, `NONE`.
- Standing contracts (rent, leasing, phone, energy) paid monthly with an amount the history
  shows may be booked without a monthly invoice, with the tax the history shows.
- Business meals: family `meals`, tax `V19` (the split into deductible and non-deductible parts is
  automatic). The firm needs the occasion and the participants.
- Devices and tools: family `equipment`, tax `V19`; the system decides by price per item whether
  it is expensed, a low-value asset (GWG, up to 800 € net) or a fixed asset.
- A Kleinunternehmer client books everything with `NONE` (also its revenue). A `befreit` client
  books purchases with `NONE` (no input VAT) and its revenue with `FREI`.
- A private purchase paid from the business account is `private_withdrawal` / `NONE`, whatever
  the receipt says.

## What the client answers (`says`)

When the firm cannot book an item from the papers it asks the client. Write what this client
would answer, per kind of question, on the events where a question is likely:

```yaml
          says:
            missing_receipt: {choice: upload}               # | {choice: no_receipt, purpose: "..."} | {choice: private}
            private_or_business: {choice: private}          # | {choice: business, purpose: "..."}
            meals_details: {choice: details, occasion: "...", participants: "..."}   # | {choice: private}
            unknown_credit: {choice: customer, invoice_no: "..."}   # | private_deposit | refund | other (note)
            invoice_incomplete: {choice: upload}            # | {choice: not_available}
          answers: false   # this client does not answer at all this month
```

`upload` sends the event's document (for an incomplete invoice, a corrected version). Answers
must agree with the truth: a client who says `private` makes the truth `private_withdrawal`.

## A realistic month

Mix: recurring bills (some with e-invoices, some PDFs, some with no paper), card payments at
places never seen before, a few new suppliers, foreign suppliers (EU and outside), a hotel stay,
business meals, a device purchase, salaries and their taxes, the VAT prepayment, the owner's
withdrawals, customer payments for invoices the client issued, and the defects real months have:
receipts that are missing, invoices that lack details, a private purchase on the business card,
an incoming payment nobody explained, an invoice paid with a cash discount, two invoices paid
in one transfer. Roughly a quarter of events should be something the system has to ask about
or a person has to look at; the rest should be ordinary.

When you are done, write `v1/README.md`: who the clients are and what you put into the month,
without the answers.
