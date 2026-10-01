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

- TODO (once stack is chosen): language, formatter, linter, and test runner.
- Until then, defaults: format everything, lint everything, tests accompany
  every behavior change.
- Never commit secrets; config via environment variables.

## Git practices

- Every new commit follows Conventional Commits as defined below.
- Keep commits small, focused, and incremental. Do not squash or rewrite
  history; fixes and reverts belong in subsequent commits.
- Branch per feature/fix; no direct pushes to main once collaboration starts.
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

## Quality gates (to be automated)

- TODO: CI pipeline — lint, typecheck, tests on every PR.
- TODO: "fitness functions" — automated checks that enforce documented
  decisions (e.g. fail PRs touching guarded code paths without an ADR update).

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
- **SessionEnd:** appends buffered summaries to `docs/devlog/YYYY-MM-DD.md`,
  using the machine's local date/time. Existing notes remain intact.
- Repeated callbacks are deduplicated, including across session resumes;
  a writer lock serializes this script's concurrent invocations.
- Only final assistant text is retained, capped at 2,000 characters per turn.
  Prompts, tool output, reasoning, and transcripts are not copied. Common
  credential patterns are redacted before buffering; this is best effort,
  so review generated notes before committing them.
- Automatic entries report what the assistant said, not independently verified
  findings. Include verification, blockers, and gotchas in final summaries
  when relevant. Continue recording decisions and Engineering Notes explicitly.
- Session-end writes depend on prior Stop events. Empty sessions write nothing.
  Failed writes report a hook error and leave buffered notes for a later retry.

Codex emits `SessionEnd` on normal close, archiving/deleting an open thread,
or after a thread is idle and not open in any client for 30 minutes. Switching
tabs or finishing a reply alone does not end a session. A force-killed process
may not emit the event. See the [official hook documentation](https://learn.chatgpt.com/docs/hooks).

The existing `.opencode/plugins/devlog.ts` remains a separate OpenCode
integration; its `session.idle` callback logs turns with different behavior.

Validate the Codex writer with:

```sh
python3 -m unittest discover -s tests -p 'test_devlog_hook.py' -v
```
