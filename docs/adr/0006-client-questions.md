# 6. Questions to clients: only what is missing, once a month

Status: accepted

## Context
The most expensive part of a close is chasing clients for receipts and explanations. A message per
item annoys them; a vague "please send everything" does not get answers.

## Decision
- The agent asks only for what blocks a correct booking: a missing receipt, private or business, the
  occasion and participants of a meal, a corrected invoice. Each question names the payment (date,
  amount, counterparty) and offers fixed answers plus the field that answer needs.
- One bundle per client and month, one link, a due date (`config/close.yaml`). The outbox worker
  sends it (SMTP) with `FOR UPDATE SKIP LOCKED`.
- Answers are applied by the same rules as everything else: "privat" books a private withdrawal, an
  uploaded receipt is read and matched like any document, and whatever the rules cannot settle goes
  to review. A client who does not answer leaves the item on the Klärungskonto, visible in the
  sign-off checks.

## Consequences
- In the blind sets 93–98 % of the questions asked were needed according to the answer key.
