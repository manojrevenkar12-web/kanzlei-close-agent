# Blind set v3

Two invented firms, five invented clients, one month (September 2026) each. Every name, address
and reference is made up; emails end in `.example`. This file describes the clients and what
happens in their month. It does not give the bookings.

## firm_a.yaml: Steuerkanzlei Wendt & Kowalczyk, Leipzig (SKR03)

### kw-4101 Zahntechnik Brückner GmbH: dental laboratory (OPOS, Soll, monthly)

A commercial dental lab with three technicians and the managing shareholder. It invoices dentists'
practices for crowns, bridges, splints and dentures, and buys alloys, ceramics, zirconia blanks
and outsourced milling. 45 events:

- six outgoing invoices to four practices; payments for four of them, including one paid with a
  customer's cash discount and one transfer covering two invoices; one invoice stays open;
- eight incoming invoices: precious-metal alloy (paid with a cash discount), two consumables
  invoices paid in one transfer, zirconia blanks from Austria, a monthly CAD software subscription
  from Switzerland, outsourced milling (XRechnung), a new sintering furnace, and a machine repair
  whose invoice lacks a detail;
- a small credit from a known supplier with a cryptic reference;
- rent with no monthly paper, electricity, phone, vehicle leasing, three fuel receipts (one sent
  only on request, one never), a business dinner with a client practice, a trade conference in
  Hamburg (fee, train, hotel with breakfast), four salaries, social security, wage tax, the VAT
  prepayment and bank charges.

### kw-4102 Backhaus Lindner e.K.: bakery with café (direct, Ist, monthly)

A craft bakery with one shop and café seating, four staff including an apprentice. Cash goes into
the till and is deposited at the bank's machine; card sales are paid out weekly by the terminal
provider, which bills its charges once a month. 42 events:

- five weekly card payouts with a takeaway/eat-in split, and four cash deposits;
- flour (two deliveries, one paid with a cash discount), dairy as XRechnung, coffee beans,
  beverages with deposit, printed paper bags and cups from Poland, two cash-and-carry visits
  (one receipt with two rates, one receipt lost);
- the till software subscription from Estonia, the terminal provider's monthly charges, rent,
  electricity, gas, a mobile contract without paper, a refrigeration repair whose invoice lacks a
  detail, a new spiral kneader, a newspaper ad, the trade-chamber contribution, insurance, fuel;
- wages, social security, three different debits from the tax office on the same day, the
  owner's withdrawal, a garden-centre purchase on the business card, and an unexplained incoming
  payment from a business that ordered cakes.

## firm_b.yaml: Lück & Brandauer Steuerberatung PartG mbB, Kassel (SKR04)

### lb-5101 Blattwerk Teehandel UG (haftungsbeschränkt): tea trader (OPOS, Soll, monthly)

Sells tea and accessories wholesale to cafés and delicatessens and to consumers through an online
marketplace based in Luxembourg. 42 events:

- six outgoing invoices (tea, sometimes with accessories on the same invoice; one delivery to
  Salzburg), the marketplace's half-month sales statement, and the marketplace's fee invoice; the
  marketplace payout covers both;
- customer payments: two invoices in one transfer, one payment from a private account with the
  reference "Tee", one open invoice;
- supplier invoices: tea from Hamburg (paid with a cash discount), teapots and cups from the Czech
  Republic, shipping boxes (XRechnung), product photos from a freelance photographer who is a
  small business, a notebook whose invoice lacks a detail, and the tax firm's own invoice;
- direct bank items: rent, fibre line, parcel carrier, an order-portal subscription from Canada and
  search ads from Ireland paid by card, a trade-fair trip to Frankfurt (train, hotel, dinner with a
  prospective customer), a lost stationery receipt, the chamber contribution, insurance, two
  salaries, social security, wage tax, the VAT prepayment and bank charges.

### lb-5102 Physiotherapie mobil Annika Rautenberg: home-visit physiotherapist (direct, tax-exempt, quarterly)

A self-employed physiotherapist who only does home visits. Statutory-insurance treatments are
billed through a billing centre that pays out twice a month and charges a fee; private patients
pay by transfer. 33 events:

- two billing-centre payouts, the centre's fee invoice, five private-patient payments (one from a
  relative with no reference), and a deposit from the owner;
- a leased car (leasing, insurance, service, three fuel receipts, one lost), a portable treatment
  table, therapy supplies (one receipt only on request), a lymph-drainage course in Hannover with
  train and hotel, a lunch with a referring orthopaedist, the association fee, the annual
  liability premium, the practice software and the tax firm's invoice;
- the owner's voluntary health insurance, a debit from the tax office, two transfers to her
  private account, a bedding order on the business card, and bank charges.

### lb-5103 Haarwerk mobil Johanna Pfeiffer: mobile hairdresser (direct, Kleinunternehmerin, quarterly)

A master hairdresser working from her car: two care homes, private clients at home and bridal
styling. 31 events:

- payments from both care homes, three card-terminal payouts, four private clients, and a
  transfer from a private person with no reference;
- hair colour from a German wholesaler and bleach from a Dutch web shop, a drugstore receipt, new
  professional scissors, a balayage seminar, flyers, stamps;
- fuel (one receipt lost), car insurance, an oil and tyre change, mobile phone, an online booking
  app from Ireland, the terminal provider's fees, the chamber contribution, liability insurance,
  bank charges;
- the compulsory pension contribution for craftspeople, a private withdrawal, and a coat bought on
  the business card.

## Coverage

Booking methods: OPOS (kw-4101, lb-5101), direct (kw-4102, lb-5102, lb-5103). VAT regimes: Soll
(kw-4101, lb-5101), Ist (kw-4102), tax-exempt (lb-5102), Kleinunternehmer (lb-5103). Periods:
monthly and quarterly. Document formats: XRechnung UBL and CII, ZUGFeRD, PDF, and no paper.
