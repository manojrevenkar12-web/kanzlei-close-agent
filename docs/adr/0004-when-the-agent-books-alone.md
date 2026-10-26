# 4. When the agent books on its own

Status: accepted

## Context
Every booking ends up in the advisor's monthly sign-off, but nobody looks at what the agent booked
on its own. So the share of those that are wrong is the number that matters, and it must be bounded
before the agent sees a new client, not hoped for.

## Decision
- A small logistic model (`config/decision.json`) estimates, per proposal, the chance that it is right
  from features the engine has anyway: how often and how consistently the client booked this
  counterparty, the classifier's probability and margin and whether it agrees, whether a structured
  invoice matched and how well, whether the tax came from the document, standing contracts, deviation
  from the usual amount, the family's risk, new counterparty, direction of the money.
- It is trained on proposals from the development months with cross-validation by client. The
  threshold is the lowest one whose **Wilson 95 % upper bound** on the wrong share among automatic
  bookings is at most 1 % (`config/release.yaml`).
- Rules can always stop a booking regardless of the score: a counterparty this client never paid
  (unless the classifier is very sure), missing receipt, asset above GWG, meals without details,
  incomplete invoice, conflict between history and text.
- The release gate fails if the development months exceed 1.5 % or a blind set 3 %.

## Consequences
- On unfamiliar firms the agent books less on its own (39–43 % on the blind sets against 89 % on the
  development months) rather than more wrongly: both blind sets have 0 wrong automatic bookings today.
