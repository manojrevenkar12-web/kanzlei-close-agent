# 1. Models read, rules decide tax

Status: accepted

## Context
A booking has two halves: what a payment or invoice is (fuel, rent, a software subscription) and how it
is taxed (19 % input VAT, reverse charge under § 13b, intra-community acquisition, not deductible
without a proper invoice). The first is a judgement from text and history. The second is law, and a
wrong VAT code goes into the Voranmeldung that the advisor signs.

## Decision
- Learning components only answer "what is it?" and return a chart-neutral **family**
  (`config/families.yaml`). They are the client's own history (memory by IBAN and name), a text
  classifier, and optionally a language model.
- The **tax code** comes from `domain/tax.py`: the invoice (category, rate, seller country, VAT ids,
  § 13b note), the client's regime (Soll/Ist, Kleinunternehmer, § 4 Nr. 14), the Pflichtangaben and
  the thresholds in `config/tax.yaml` (Kleinbetrag 250 €, GWG 800 €, meals 70 %).
- The **account** comes from the chart mapping (`config/charts/skr03.yaml`, `skr04.yaml`): family + tax
  code to account and BU key. One family list serves both charts and acquired firms' own accounts.
- Every proposal carries its reasons ("Bisher 5× gebucht …", "Steuer laut Rechnung: V19"), so the
  reviewer sees why.

## Consequences
- A model that misreads an invoice can pick the wrong family, but it cannot invent a tax treatment.
- New tax rules are code with tests (`tests/test_rules.py`), not prompt changes.
- Adding a chart is a YAML file, not a retraining.
