# 5. Evaluation against known answers, with blind sets

Status: accepted

## Context
Real client data cannot be used to develop this, and a demo on hand-picked examples proves nothing.

## Decision
- `kanzlei_sim` simulates firms: clients with a year of DATEV history, a month of CAMT.053 bank
  statements and the documents that come with it (XRechnung UBL and CII, ZUGFeRD, PDF with and
  without text), clients who answer questions (or do not), a reviewer and an advisor. An independent
  truth builder (`truth.py`) writes the correct booking for every event; the engine never imports it
  (`tests/test_isolation.py`).
- `evaluate` closes each month end to end in a fresh database and compares every booking and every
  VAT Kennzahl with the truth.
- **Blind sets** are written by someone who has not seen the code, from `blind/WRITING_CASES.md` only.
  A set is committed before it runs; its first run goes to `reports/blind/<set>/FIRST_RUN.json` and is
  never rewritten (CI fails on any diff). Once its failures are studied, the set gets
  `STATUS=regression` and a new one is commissioned.

## History
- v1 first run: 5 of 100 automatic bookings wrong, VAT exact in 2 of 5 months. Studied, fixed, now a
  regression set: 0 wrong, 5 of 5 exact.
- v2 first run (after those fixes, unseen): 0 of 95 automatic bookings wrong, VAT exact in 6 of 6
  months, all months signed off.
