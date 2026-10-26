# Research behind the design

What the brief is, who already does what, and where this project chose to be different. Checked in
October 2026; sources at the end.

## The company and the role

Limetax builds a group of tax firms in Germany and runs them on its own agent platform on top of DATEV.
It was founded in January 2026, reported 36 M€ in September 2026 (6 M€ equity led by Motive Partners,
30 M€ credit line from German banks), about 150 people in four firms with seven locations. Its agents
take repetitive work in bookkeeping, payroll and annual accounts; the firms' staff review the results
and keep professional responsibility. One quoted case went from about 20 to 6 hours of monthly work.

A Forward Deployed Engineer there sits with the firms the group buys: gets a new firm's data in, makes
the agents fit how that firm works, and measures whether it actually saves time.

## What already exists

- **DATEV's own services.** Automatisierungsservice Bank (2024) proposes ledger bookings from bank
  transactions, learning from each client's past bookings; about 7,400 firms and over 10 M proposals a
  month. Automatisierungsservice Rechnungen does the same for invoices (over 9,000 firms). Both stop at
  proposals inside DATEV.
- **Document and bookkeeping tools** (Finmatics, Candis, docunest and others) read invoices and
  push bookings to DATEV; most are sold per firm or per company.
- **Typical demo projects** for roles like this: an OCR-to-DATEV invoice reader, or a chatbot over tax
  law. Neither closes a month, and neither says how often it is wrong.

## Where the work is

- **E-invoicing.** Every German business must be able to receive e-invoices since 1 January 2025
  (XRechnung or ZUGFeRD, EN 16931). Issuing becomes mandatory in 2027 for turnover above 800 k€ and in
  2028 for everyone; until then PDFs and paper still arrive. So a close has to read all of them, and the
  structured ones exactly.
- **Retention.** Since BEG IV, Buchungsbelege are kept 8 years (previously 10), in the form they
  arrived in.
- **Confidentiality.** § 62a StBerG: a firm may involve an IT or AI provider only with a confidentiality
  agreement in text form that warns of § 203 StGB, on a need-to-know basis, and with comparable
  protection abroad; a GDPR processing agreement alone is not enough.
- **The output is DATEV.** Firms import a Buchungsstapel in the EXTF format (semicolon CSV, header line,
  column line, rows) and keep DATEV as the books of record.
- **The VAT return** is a set of Kennzahlen (81, 86, 41, 21, 60, 48, 46/47, 84/85, 89, 66, 61, 67, 83) with
  bases in whole euros and tax in cents, monthly or quarterly, with a Dauerfristverlängerung for many.

## Choices this led to

1. **Close the month, not just propose bookings.** Bank statement and documents in; matched, booked,
   asked, reviewed, VAT return, sign-off with Festschreibung, EXTF out. That is the unit of work a
   firm is paid for.
2. **Measure wrong bookings, before and after.** A simulation with an independent answer key, and
   blind sets written by someone who never saw the code, with first runs that are never rewritten.
3. **Rules decide tax.** Models only say what something is (ADR 1); § 13b, intra-community supplies,
   Kleinunternehmer, meals, GWG and Pflichtangaben are code with tests.
4. **Built for a group that buys firms.** Tenancy in Postgres, onboarding from DATEV history with
   account mapping, and a rollout view of numbers per firm without client data.
5. **The model is optional** and gated by the § 62a agreement date; everything is measured without it.

## Sources

- [Limetax erhält 36 Millionen Euro (startbase, 9 Sept 2026)](https://www.startbase.com/news/limetax-erhaelt-36-millionen-euro-fuer-ki-getriebene-steuerkanzleigruppe/)
- [Limetax raises 6M pre-seed (Dealroom)](https://dealroom.co/news/149645-limetax-raises-6m-pre-seed-to-roll-up-germanys-tax-firms-with-ai/)
- [DATEV: Starkes Wachstum bei KI-Services für das Rechnungswesen (2026)](https://www.datev.de/web/de/berufsgruppenuebergreifend/presse/presseinformationen/meldungen-2026/starkes-wachstum-bei-ki-services-fuer-das-rechnungswesen)
- [DATEV developer portal: DATEV-Format (EXTF)](https://developer.datev.de/datev/platform/en/dtvf)
- [E-Rechnungspflicht 2025–2028 (ADVISORI)](https://www.advisori.de/blog/e-rechnungspflicht)
- [IHK Karlsruhe: 4. Bürokratieentlastungsgesetz](https://www.ihk.de/karlsruhe/fachthemen/steuerrecht/aktuelles/neuer-inhalt4-buerokratieentlastungsgesetz-6347138)
- [Deubner: § 62a StBerG und KI in der Steuerkanzlei](https://www.deubner-steuern.de/themen/digitalisierung-steuerberatung/ki/62a-stberg.html)
