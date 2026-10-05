# Contributor connector execution logs

Requested October 4, 2026: show collection, comparison/skip decisions and S3
seeding step by step during explicit connector executions. Candidate CLI runs now
persist by default under ADR-0042; `--local-only` explicitly opts out.

## Behavior

- Candidate, persist and recover commands emit timestamped INFO diagnostics to
  stderr by default. Final status and exact manifest references stay on stdout.
  Help emits no execution logs or work. Imports do not configure logging.
- Candidate logs identify the run, interval, EIA route, metadata/page requests,
  offsets, attempts/retries, row counts, empty termination, local evidence,
  comparison, per-grain quality/retention counts, replay verification and outcome.
- Per-grain comparisons distinguish excluded invalid rows, identical duplicates,
  superseded valid conflicts, retained invalid/absent prior rows and output counts.
  Exclusion-reason occurrences are separate from excluded-row counts. Summaries
  do not dump individual records or infer upstream completeness/revision recency.
- Existing policy remains: the last valid observation in recorded source order
  wins a valid conflict; duplicates collapse, invalid incoming values are excluded,
  and prior valid rows survive invalid or absent replacements. This request adds
  diagnostics, not a new rule to skip all valid conflicts.
- Persistence verifies the local graph, transfers dependencies before the final
  manifest, and performs complete readback/replay before logging a verified
  durable outcome. S3 logs conditional attempts, retries and hash/byte readback.
  Existing objects are logged as skipped only after identical bytes are verified.
  Conflicting bytes abort and preserve the object; they cannot confirm success.
- Recovery logs exact object identities, restoration and full replay with EIA
  disabled. A receipt does not activate a backend generation.
- Diagnostics use fixed names, contract reasons, counts and exact content/run
  identities. Never log URLs/query strings, headers, raw records, unexpected
  field names, credentials or exception text. CLI failures use safe codes.
- Application diagnostics are injected through a port and cannot decide success.
  CLI installs/restores only its named logger handler/settings, leaving root,
  SDK and HTTP wire logger configuration alone. Durable JSON reports remain the
  outcome record; terminal logs are not backend refresh outcomes.

## Verification

Controlled tests verify multipage collection and comparison order/counts with
real Parquet; retained graph persistence/recovery; identical-skip versus conflict
rejection; retry/error sanitization; help and logger cleanup; and application
observer failure without altered outcomes. No live EIA or AWS checks are needed.

Verification on October 4, 2026: `make check` passed dependency validation,
Ruff lint/format, strict mypy (56 source files), 812 tests and wheel/sdist builds.
These are controlled local checks; no live EIA/AWS calls were made.
