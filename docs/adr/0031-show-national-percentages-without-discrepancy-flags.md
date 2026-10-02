# ADR-0031: Show national percentages without discrepancy flags

Status: **Accepted**

Date: 2026-10-01

## Context

ADR-0006 retains EIA's reported percentage alongside the calculated daily
national offline share. During the requirements discussion, the user clarified
that both come from the same stored daily observation. No live API lookup or
matching against a newly fetched record is involved in this verification.

The user accepted preserving calculation precision and rounding percentages to
two decimal places with halfway values rounded up. After discussing a proposed
match/mismatch classification, the user directed: "dont add a mismatch/match
just display the data, dont flag out the discrepancy".

## Decision

- Show the calculated and EIA-reported percentages together for each daily
  national observation, using that observation's stored capacity, outage and
  reported percentage.
- Preserve calculation precision. For presentation at two decimal places,
  round halfway values up and preserve the original source percentage as
  evidence. This is our presentation rule, not a claim about API internals.
- Do not classify the two values as match/mismatch or add discrepancy flags,
  warnings, alerts or discrepancy counts, including in verification output.
- A difference alone does not exclude an otherwise usable observation, replace
  either value or cause verification to fail. No agreement tolerance is needed.
- Verification continues to establish that the calculation follows the agreed
  formula using the recorded inputs. Arithmetic or transformation errors remain
  failures; agreement with the reported percentage is not a correctness oracle.

This refines the comparison behavior left open in ADR-0006. Required-field
validation and exclusion accounting under ADR-0023/0027 remain applicable.
Cross-grain reconciliation is a separate effort. Showing the data does not
introduce frontend work or select a new delivery mechanism.

## Alternatives and consequences

Match/mismatch classification would add a simple diagnostic, but the user
selected displaying the values without that extra interpretation. Excluding
observations solely because the percentages differ would discard potentially
usable evidence and is not selected.

Consumers can inspect both values. The application does not automatically
highlight differences or assert that agreement proves physical accuracy.

## References

- [Requirements brief](../specs/national-data-verification/requirements.md)
- [ADR-0006: Daily fleet offline share](0006-daily-fleet-offline-share.md)
- [ADR-0027: Required national values](0027-national-required-values-and-positive-capacity.md)
