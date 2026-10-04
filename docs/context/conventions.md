# Conventions & Good Practices

How we work in this repo. AI agents and humans both follow this; if a rule
is wrong, propose a change here rather than silently deviating.

## Documentation discipline

- **Decisions → ADRs.** Any choice that is hard to reverse or that future
  contributors will ask "why?" about gets a numbered record in `docs/adr/`
  (MADR-style: context, options with pros/cons, decision, consequences).
  One decision per file. Supersede, don't rewrite.
- **Features → specs first.** Before building a feature, write
  `docs/specs/<feature>/spec.md` (what & why, EARS-style requirements).
  Plan and task breakdown follow before implementation.
- **Day-to-day → devlog.** Append-only journal in `docs/devlog/YYYY-MM-DD.md`:
  what was done, blockers, gotchas. When a devlog entry contains a real
  decision, promote it to an ADR the same day while context is fresh.
- **This folder (`docs/context/`) is living documentation** — update it when
  reality changes, unlike ADRs which are immutable once accepted.

## Code practices

- Follow the accepted [layered monolith structure](code-structure.md) and root
  [AGENTS.md](../../AGENTS.md). Their dependency matrix governs new application
  code; ADR-0030 replaces the earlier feature-first proposal.
- Python >=3.12; Flask 3.1 for HTTP. Use Ruff for scaffold formatting/linting,
  mypy strict mode for application source, and pytest for behavior and architecture
  tests. Configuration lives in `pyproject.toml`; resolved development dependencies
  live in `requirements-dev.txt`. Existing devlog tooling retains its independent
  standard-library checks and is excluded from Ruff to avoid unrelated rewrites.
- Tests accompany every behavior change. No Flask/AWS/database dependencies in
  pure use-case tests; inject application ports.
- Never commit secrets; supply credentials through the environment. Connector
  resource limits use typed defaults with optional `--config PATH` JSON overrides,
  not `OUTAGE_CONNECTOR_*` variables ([ADR-0041](../adr/0041-connector-defaults-and-json-configuration.md)).

## Git practices

- Every new commit follows Conventional Commits as defined below.
- Keep commits small, focused, and incremental. Do not squash or rewrite
  history; fixes and reverts belong in subsequent commits.
- Work directly on `main` for this project. Commit and push approved changes to
  `main`; do not create additional branches unless the user explicitly requests one.
- TODO: PR review expectations.

### Commit message structure

```text
<type>(<scope>): <summary>

<optional body explaining why>

<optional footers>
```

| Type | Use |
|------|-----|
| `feat` | Add a capability |
| `fix` | Correct a bug |
| `docs` | Change documentation only |
| `refactor` | Restructure code without changing behavior |
| `test` | Add or change tests |
| `chore` | Maintenance and development tooling |
| `build` | Dependencies or build configuration |
| `ci` | CI workflow changes |
| `perf` | Improve performance |
| `revert` | Revert an earlier commit |

- Write commit messages in English.
- Use a lowercase type and an optional lowercase scope. Suggested scopes:
  `connector`, `model`, `auth`, `catalog`, `query`, `refresh`, `devlog`, `project`.
- Keep the complete subject within 72 characters, start the summary with an
  imperative verb (for example, `add` or `fix`), and omit the trailing period.
- Separate the optional body and footers with blank lines. Use the body to
  explain why the change is needed, including relevant tradeoffs.
- Mark breaking changes with `!` before the colon and include a
  `BREAKING CHANGE:` footer explaining the incompatibility and migration.
- For a revert, identify the reverted commit and explain why in the body.

Examples:

```text
feat(connector): ingest national outage data into Parquet
fix(auth): reject Viewer queries against facility datasets
docs(model): explain the fleet offline capacity metric
chore(devlog): add automatic session logging hooks
```

Breaking-change example:

```text
feat(query)!: require a dataset name in query requests

Make dataset selection explicit before authorizing a query.

BREAKING CHANGE: Query requests now require a dataset field. Update API
clients to send the authorized dataset name with each request.
```

## Quality gates

- `.github/workflows/ci.yml` runs Ruff lint/format, mypy, pytest, and package
  build checks on pushes and PRs using Python 3.12 and 3.14. See README for the
  same local commands. A configured workflow is not evidence of a remote CI run.
- Import-boundary checks under `tests/architecture/` enforce the structure
  guide's matrix, including relative imports, re-exports, cycles, the narrow
  bootstrap startup exception, and negative fixtures. Behavior tests must
  separately verify authorization, publication, and execution isolation when
  those use cases are implemented.

## AI agent practices

- Agents read `AGENTS.md` at the repo root before working.
- Agents write ADR drafts but a human approves them; agents never silently
  make architecturally significant choices.
- Agents keep `docs/context/` in sync when code reality diverges from it.

## Automatic Codex devlog

Repo-local hooks in `.codex/hooks.json` run `scripts/devlog_hook.py` with Python
3 (standard library only; macOS/Linux). Review and trust both hooks in Codex's
`/hooks` menu, then use a new or resumed session with this repository loaded.
The repository itself must also be trusted. No global hook configuration is
changed by this setup.

- **Stop:** buffers the final assistant summary after each completed turn in
  gitignored `.devlog-state/`. It does not append to the journal yet.
- **PreToolUse (Bash):** before a literal `git commit` command, appends pending
  summaries from this repository’s buffered sessions to `docs/devlog/YYYY-MM-DD.md`,
  using the machine’s local date/time. This includes sessions already closed.
  Existing notes remain intact. Session close no longer writes the journal.
- When new notes are appended, the hook blocks that tool call and tells Codex
  to review and stage the notes, then retry the commit. It does not require user
  confirmation, stage files itself, or create commits. Retries do not duplicate
  notes or block again when there are no new summaries.
- Repeated callbacks are deduplicated, including across session resumes;
  a writer lock serializes this script's concurrent invocations.
- Only final assistant text is retained, capped at 2,000 characters per turn.
  Prompts, tool output, reasoning, and transcripts are not copied. Common
  credential patterns are redacted before buffering; this is best effort,
  so review generated notes before committing them.
- Automatic entries report what the assistant said, not independently verified
  findings. Include verification, blockers, and gotchas in final summaries
  when relevant. Continue recording decisions and Engineering Notes explicitly.
- Writes depend on prior Stop events. Work in the current unfinished turn has
  no final summary yet; Codex should record that work explicitly before committing.
  Empty buffers write nothing. Failed pre-commit writes block the command and
  preserve recoverable notes for retry.
- Detection covers literal `git commit`, Git global options and shell command
  chains. Non-commit commands and `git commit --dry-run` do not flush notes.
  This is a Codex tool hook, not a native Git hook: commits made outside Codex,
  through aliases, wrapper scripts or dynamically constructed shell commands
  are not covered. Run commits for this repository from its working tree.

After changing the configuration, review and enable **PreToolUse** in `/hooks`
(and keep **Stop** enabled), then start or resume a session to load it. The old
SessionEnd trust entry does not enable the new event. See the
[official hook documentation](https://learn.chatgpt.com/docs/hooks).

The existing `.opencode/plugins/devlog.ts` remains a separate OpenCode
integration; its `session.idle` callback logs turns with different behavior.

Validate the Codex writer with:

```sh
python3 -m unittest discover -s tests -p 'test_devlog_hook.py' -v
```
