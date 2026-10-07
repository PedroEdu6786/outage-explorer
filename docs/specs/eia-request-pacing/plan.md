# Implementation plan

Add a thread-safe monotonic admission limiter in infrastructure/eia, owned by
SourceRunBudget and reused by its EiaSource adapters. A standalone adapter owns
its own limiter. Admit only when spacing and shared cooldown both expire; never
reserve future slots, so delayed threads cannot release a catch-up burst. Sleep
outside locks in short increments, rechecking cancellation and deadlines.

Extend SourceBounds/SourceSettings with request_interval_milliseconds and
backoff_base_seconds. Keep current bounded Retry-After parsing and feed the
computed cooldown into shared admission for 429 and retryable Retry-After.
Existing bootstrap budget sharing applies to both CLI and refresh workers.

Test virtual-clock pacing/backoff/header/deadline cases, real concurrent shared
admission and cancellation, config validation, existing connector integration
and architecture checks. Update contributor documentation and append the devlog.
