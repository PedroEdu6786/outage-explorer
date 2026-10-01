# ADR-0009: Focus ingestion and refresh on recent dates

Status: **Accepted direction; exact dates pending source inspection**

Date: 2026-10-01

## Context and decision

The user selected recent dates within the challenge's required range rather
than a full-history ingestion. The original challenge, Part 2, requires a
reconciliation interval of **at least 30 days of our choice**; it specifies
no fixed calendar dates or rolling refresh window.

Use a recent selected period across all three routes. The proposed initial
default is the latest complete 30-calendar-day interval available across
the routes. Verify availability before fixing its end date; do not assume
today's observations are complete. Record the exact dates used for findings.
The refresh window's anchoring and replacement mechanics remain to be
validated. Recent-only refresh does not discover corrections outside it.

## Alternatives and consequences

Full-history extraction increases scope without a challenge requirement.
A recent bounded interval meets the user's direction; a longer investigation
may still be necessary to find three genuine anomalies. Never manufacture
anomalies to fit the interval. Source keys, completeness and data rules remain
investigation work.

Source: local `Software Engineer - Technical Challenge.pdf`, Part 2,
re-read on 2026-10-01.
