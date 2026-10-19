# Existing local runtime rebuild

Accepted under [ADR-0066](../../adr/0066-unattended-local-runtime-rebuilds.md).

1. `make local-rebuild` shall run without terminal input or a reviewer argument.
2. It shall export current allowlisted source, tests, scripts, build inputs and
   required contracts; ignore deleted files, exclude credentials/generated files,
   reject symlinks, and never mutate the index, working tree or stash.
3. It shall reuse the installed guest and retain spill, cache, settings, ownership
   locks and ledgers. Missing/broken infrastructure shall fail with the stage name.
4. It shall stop the local API, reject unresolved workloads, stage a fresh Python
   environment and worker image, and preserve the previous source and evidence.
5. It shall re-run all required controlled, parser and containment tests and the
   exact parser smoke checks before emitting automated local-only evidence.
6. Failed/skipped/incomplete/mismatched checks shall prevent configuration.
7. Successful configuration shall leave the API stopped. Recovery shall support
   resuming after a completed update and restoring the previous build, without
   deleting failed evidence, recreating the VM or starting refresh.

## Implementation sequence and acceptance

- Add working-tree snapshot and staged guest update/recovery orchestration.
- Add explicit automated-evidence type metadata and local-only admission checks.
- Wire no-prompt Make commands and document runtime state/recovery behavior.
- Verify source edits/additions/deletions/exclusions, repeated updates, failure
  ordering, preserved backups, strict evidence and prompt-free orchestration with
  controlled tests. Report actual-host execution separately from these tests.
