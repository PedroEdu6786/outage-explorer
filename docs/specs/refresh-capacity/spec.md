# Refresh capacity for the configured interval

User direction, October 8, 2026 UTC: increase the row cap. The current local
start is November 1, 2025; through October 8, 2026 it spans 342 days. Using the
previously observed one national, 55 facility and 95 generator rows/day gives
51,642 rows. This is a sizing fixture, not a guaranteed current source roster.
The older September 1, 2025 start spans 403 days and approximately 60,853 rows.

- Source defaults SHALL allow 100,000 aggregate rows, 250 pages and 500 requests
  including retries. Existing aggregate enforcement SHALL remain active.
- Model incoming/prior/output defaults SHALL allow 100,000 rows per grain, so
  a successful larger generation can also be retained and refreshed again.
- CLI and product refresh SHALL share these typed defaults. Explicit CLI JSON
  overrides SHALL retain precedence. HTTP dates SHALL remain frozen at admission
  under ADR-0063; CLI date limits SHALL retain their existing behavior.
- Existing byte, file, memory, disk, elapsed, attempt and concurrency limits SHALL
  remain enforced, as SHALL two-request/second pacing and shared retry cooldowns.
- Controlled source collection, exact three-resource verification and a subsequent
  retained-prior update SHALL succeed for the 342-day fixture. Resource exhaustion
  SHALL continue to fail closed without publication.

This increases finite contributor allowances, not arbitrary-history support or
measured live/production budgets. It does not change the accepted architecture
or authorize a live refresh, service restart or publication.
