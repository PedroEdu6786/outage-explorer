# ADR-0066: Rebuild the existing local runtime without interactive acceptance

Status: **Accepted by explicit user direction**

Date: 2026-10-19

## Context

The user requested rebuilding current project changes in the existing Colima VM,
then explicitly removed reviewer-name and confirmation prompts. The earlier
`local-rebuild` only wrapped fresh installation and required manual acceptance.

## Decision

- `make local-rebuild` snapshots current allowlisted working-tree files, including
  uncommitted edits, additions and deletions, without changing Git state. It reuses
  the existing VM, daemon, spill filesystem, settings and ownership metadata.
- Build a separate replacement source/environment/image. Stop the API cleanly
  and verify quiescence before installation. Preserve previous source, profiles
  and reports outside active lookup paths. Each replacement environment stays at
  its build path; the fixed API source path links to that release so virtualenv
  entry points remain valid. Never delete the VM or reset data.
- Re-run controlled, parser and actual-host containment checks for the new
  identities. Record automated validation explicitly, with no fictitious human
  reviewer. All existing required gates and parser smoke checks remain mandatory.
- Automated evidence is admissible only for the local preview/SQL scope with
  refresh idle. It does not establish full capacity, external-service acceptance,
  production readiness or publication permission. This supersedes ADR-0055's
  per-rebuild human-review requirement only for this local update workflow.
- Configure only after validation passes. Leave the API stopped. On failure,
  preserve previous build/evidence and provide explicit resume/rollback commands.
  No user confirmation is requested by rebuild or recovery commands.

## Consequences

Initial installation retains its existing separate commands. Rebuild requires a
usable installed runtime; broken or missing prerequisites produce actionable
errors instead of silently provisioning or deleting resources. Automated and
human evidence remain distinguishable and mismatched identities fail closed.
