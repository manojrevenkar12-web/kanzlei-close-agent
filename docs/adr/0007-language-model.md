# 7. The language model is optional and bound by § 62a StBerG

Status: accepted

## Context
A model is useful for PDFs without e-invoice data and for counterparties nobody has booked before. But
a tax firm may hand client data to a provider only with a confidentiality agreement in text form that
warns of § 203 StGB, on a need-to-know basis, and with comparable protection abroad. A GDPR processing
agreement alone is not enough.

## Decision
- Off unless `ANTHROPIC_API_KEY` is set **and** the firm's agreement date is recorded
  (`firms.llm_agreement_on`).
- Only the uses in `config/llm.yaml`; IBAN, e-mail, phone and tax ids are removed first.
- A model's reading of an invoice is accepted only if its lines add up to the total
  (`tests/test_isolation.py`), and it still only proposes a family (ADR 1).
- All numbers in `reports/` are measured without a model.

## Consequences
- The product works, and is measured, for firms that have not signed such an agreement.
