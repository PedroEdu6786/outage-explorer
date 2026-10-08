# EIA request pacing and retries

User request: October 7, 2026. Reduce EIA throttling with longer retries and
request pacing, preserving existing bounded retrieval and publication behavior.
The user subsequently selected two requests/second (500 ms spacing) on the same
date, replacing the initial one-request/second default.

- Every metadata, page and retry attempt SHALL acquire a shared per-run request
  slot across endpoint/page workers. Default spacing is 500 milliseconds, with
  no accumulated burst credit. Standalone source adapters SHALL also be paced.
- Retry backoff SHALL use a configurable 10-second base and 120-second cap,
  exponential growth and 50–100% jitter. Five total attempts and 30-second
  network-phase timeouts remain the defaults.
- A retryable HTTP response with Retry-After, or HTTP 429 without it, SHALL defer
  all new admissions in that run for at least the computed bounded delay.
  Already in-flight requests may finish. Numeric and HTTP-date Retry-After
  remain supported; values over the cap fail closed without an early retry.
- Pacing and backoff SHALL remain cancellable and count against existing elapsed
  deadlines. Rechecking after sleeps SHALL prevent late attempts. Attempt and
  aggregate resource limits, sanitization and nonretryable failures remain intact.
- Positive integer JSON overrides SHALL use existing source configuration. No
  distributed rate coordinator, source rerun, deployment or publication is added.

EIA's [official FAQ](https://www.eia.gov/opendata/faqs.php), checked October 7,
2026, advises sustained rates below approximately 9,000/hour and bursts below
5/second under ideal conditions. Throttling also depends on key usage, IP and
series demand; complex routes may have lower limits. Temporary bans may last
seconds or minutes. These guidelines are not guaranteed quotas. Our default is
approximately 7,200/hour; independent processes/other key or IP users are outside
the per-run limiter. This is resource tuning, not a changed architecture boundary.
