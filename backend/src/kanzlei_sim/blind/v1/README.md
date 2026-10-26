# Blind set v1

Two invented tax firms with five clients between them, each with one month of bank account
(September 2026), the receipts and invoices that came with it, and a history of earlier months.
All names, addresses and reference numbers are made up. Emails end in `.example`; IBANs and VAT ids
are generated.

| File | Firm | Chart | Clients |
| --- | --- | --- | --- |
| `firm_a.yaml` | Steuerkanzlei Wendelin & Rauh, Leipzig | SKR03 | a-1001, a-1002, a-1003 |
| `firm_b.yaml` | Ahrens Thormählen Steuerberatungsgesellschaft mbH, Kassel | SKR04 | b-2001, b-2002 |

## The clients

**a-1001 Tischlerei Kornmayer e.K.** (OPOS, Soll-Versteuerung, monthly return, 43 events).
A joinery doing interior fit-out and furniture, with two journeymen and an apprentice. It works for
a general contractor on a housing project and for private and commercial customers. It buys timber
from a regional wholesaler, fittings from Austria, and has a German installation firm working on
the building site for it. The month has issued invoices and their payments, purchase invoices and
their payments, the usual direct debits, card payments at the petrol station and DIY and garden
stores, a business lunch, a new machine and a cordless tool, payroll with social security and wage
tax, the August VAT return and other debits from the tax office, a legal bill, a newspaper ad, the
guild fee, and the owner's withdrawal.

**a-1002 Johanna Peschel UX Design** (direkt, Ist-Versteuerung, quarterly return, 32 events).
A freelance UX designer working from a coworking space for a Leipzig mobility start-up, a Dutch
studio, a cultural association and a new small customer. She uses German, Irish and US software
subscriptions, went to a two-day conference in Hamburg (train, taxi, hotel), bought a new laptop,
hired a freelance illustrator, and pays a private health insurer and the tax office from the
business account. The month also has two meals out, office supplies, printing, a clothes
purchase, and owner withdrawals.

**a-1003 Tonhaus Ilse Brecht** (direkt, Kleinunternehmerin under § 19 UStG, 32 events).
A pottery studio that sells at weekend craft markets (card terminal payouts and cash), through a
café on commission, and teaches pottery courses. The month has studio rent, clay and glaze
purchases, a new potter's wheel, a kiln repair, a shelf, a market stand fee, flyers, a workshop she
signed up for, a dinner with a gallery owner, a drugstore purchase, a cash deposit, a transfer
from her husband, and her withdrawals and health insurance.

**b-2001 Physiotherapie am Fuldaufer Katrin Sommerfeld** (direkt, tax-exempt medical practice,
38 events). A practice with three therapists and a receptionist on a mini-job. Income comes from
the statutory insurance billing centre and from private patients' invoices. The month has rent,
car leasing for home visits, practice supplies, a new electric treatment couch, a training course
in Göttingen with train and hotel, a lunch with a cooperating orthopaedist, an ad, payroll with
social security and wage tax, the owner's withdrawals, a toy shop purchase, a small payment with
no clear reference, and a credit from an insurer.

**b-2002 Blattwerk Teehandel GmbH** (OPOS, Soll-Versteuerung, monthly return, 44 events).
An online shop for loose tea (7 %) and tea accessories (19 %), selling to consumers through its
shop (weekly payouts from the payment provider) and to cafés and organic shops in Germany and a
tea salon in France. It buys tea from a Hamburg importer and a herb supplier, ceramics from the
Netherlands, ships through a parcel service, advertises with an Irish ad network, and uses a US
label tool. In September it exhibited at a trade fair in Frankfurt (stand fee, train, hotel, a
dinner with a customer, a taxi). The month also has a label printer and parcel scale, warehouse
shelving, a lawyer's bill about a cease-and-desist letter, payroll and taxes, and the August VAT
return.

## What the month contains

Across the five clients:

- recurring bills with e-invoices (XRechnung UBL and CII, ZUGFeRD), with plain PDFs, and with no
  paper at all for standing contracts;
- card payments at places the client has never used before;
- foreign suppliers inside the EU (goods and services) and outside the EU (software);
- customers in another EU country (goods and services) and a general contractor;
- hotel stays with room and breakfast at different rates, train tickets, a taxi;
- business meals, some with the occasion and participants on the bill and some without;
- devices and tools at different prices;
- payroll, social security (including a mini-job), wage tax, the VAT prepayment and other debits
  from the tax office;
- owner withdrawals and a private deposit;
- and the defects of a real month: receipts that arrive only when asked and receipts that never
  come, invoices missing mandatory details (some corrected on request, one not), private purchases
  on the business card, incoming payments without a usable reference, purchase and sales invoices
  paid with a cash discount, two invoices paid in one transfer, and a purchase invoice still open at
  month end.

Roughly a quarter of each client's events need a question to the client or a closer look. The
client's answers are in the files (`says`). The answer key is in `truth`.
