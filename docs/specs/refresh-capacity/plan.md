# Plan and tasks

Raise SourceSettings row/page/request defaults and ModelSettings incoming/prior/
output defaults; existing CLI and refresh bootstrap wiring consumes both. Keep
all other bounds and scope unchanged. Update configuration expectations and
contributor guidance, preserving historical ADRs and the append-only devlog.

- [x] Update shared typed defaults and configuration assertions.
- [x] Run a controlled 342-day/51,642-row source-to-Parquet candidate and verify
      a subsequent partial refresh retains the larger prior generation.
- [x] Verify explicit/aggregate caps and architecture; run Ruff and mypy.
- [x] Record verification and commit the bounded capacity change.
