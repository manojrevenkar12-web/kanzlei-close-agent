# 8. Onboarding an acquired firm from its DATEV history

Status: accepted

## Context
The group grows by buying firms that already work in DATEV, each with its own chart (SKR03 or SKR04),
its own extra accounts and years of bookings. The agent is only useful from day one if it learns from
that history.

## Decision
- A firm package is `firm.json` plus DATEV EXTF files: Buchungsstapel per client and year, and
  Debitoren/Kreditoren master data. `kanzlei onboard <dir>` imports it as system.
- Each historical line is mapped back to a family through the firm's chart; accounts the standard chart
  does not know are listed in the rollout view under "Konten ohne Zuordnung" and mapped there by the
  group or an advisor. The import reports mapping coverage (`tests/test_db.py`).
- Client memory (counterparty to family, by IBAN and name) is built from that history.
- Export is the same format back: an EXTF Buchungsstapel with the Festschreibung flag, plus master
  data, so DATEV stays the books of record.
