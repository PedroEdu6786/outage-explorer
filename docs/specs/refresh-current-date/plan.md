# Implementation plan

1. Keep startup settings for the strict ISO start date and non-date budgets only.
2. In bootstrap's injected configuration callback, read the existing UTC system
   clock on admission and construct a `RefreshConfiguration` with the inclusive
   span in all three interval fields. Reject future starts as invalid requests.
3. Remove the domain's hard 183-day ceiling; retain positive bounds, interval
   consistency, immutable snapshots and the separate initial-load requirement.
   The worker already maps snapshot interval fields into source/model bounds.
4. Test startup parsing, midnight/replay behavior, long spans and future rejection
   with controlled dependencies; verify larger worker intervals using controlled
   source/S3 and disposable PostgreSQL when available. Update operator guidance.
5. Run targeted tests, import boundaries, Ruff and mypy. No live refresh/restart.
