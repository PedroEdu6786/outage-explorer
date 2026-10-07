# Engineering Notes

These notes cover my work on both `outage-explorer` and `outage-explorer-web`.
They describe how I used AI, where I intervened, and how I checked the result.

## My contribution and AI's contribution

I used Codex for most of the implementation. My contribution was primarily
planning, architecture, decisions and validation rather than writing most of
the application code by hand.

I wrote the initial plan, selected the technology stack, defined how the data
connector should work, and developed the AWS infrastructure and tooling
requirements. I worked through the data model and validation rules, including
the planned modeling and validation CLIs. For the frontend, I also defined the
specifications and plans, selected the technologies, and chose the atomic
design architecture. I manually validated the use cases.

I developed skills for the spec-driven development phases: requirements,
specification, plan, tasks and implementation. For more complex planning, I
used a planning council with agents assigned to its roles. I also created
dedicated AWS and GitHub agents to guide work with those tools.

Codex translated this direction into most of the application code and helped
produce tests and supporting documentation. I reviewed its work and requested
changes when behavior, scope or readability did not match the plan.

## Development and acceptance workflow

I followed spec-driven development: requirements → specification → plan →
tasks → implementation. I considered an implementation ready to accept after
it had gone through that flow, including review and validation of the intended
behavior. Complex choices went through planning-council discussion before
implementation.

This helped pin down expected behavior before coding. It did not eliminate the
need to test the integrated application or revisit decisions when actual use
exposed a problem.

## What AI got wrong and how I caught it

Codex sometimes began implementing before planning was finished and expanded
the work into AWS resource exploration. I noticed this while reviewing its
actions against the current planning stage. I had to restrict its behavior and
use the dedicated agent workflows to keep implementation within the intended
scope and sequence.

AI also produced code that was difficult to read. I reviewed it and requested
revisions rather than accepting implementation solely because it worked.
Clear specifications were useful, but they did not replace code-quality review.

## Verification beyond running generated code

I created the challenge's persona users and manually exercised the use cases.
I sent Postman requests through every endpoint and used multiple SQL examples
to check the SQL workspace, including denial behavior. I also saturated the
query engine and tested dates outside the collected data range.

Manual testing exposed a significant issue with the initial Parquet layout:
queries could not execute in the original setup. The recorded investigation
identified a [549-file request exceeding the launcher's argument bound](docs/specs/analytical-runtime-reassessment/council/03-decisions.md#d2--evaluate-one-sealed-request-directory-mount) before
container creation. This was a runtime integration problem, rather than proof
that DuckDB could not execute the SQL. The subsequent layout decisions are
recorded in [ADR-0057](docs/adr/0057-single-file-modeled-datasets.md) and
[ADR-0060](docs/adr/0060-persist-only-three-resource-files-per-generation.md).

I also noticed unnecessary repeated data requests during application use.
After the Parquet refactor, I inspected S3 and found that artifacts from the
previous layout remained and were still being generated. That prompted a
further cleanup of the generation and persistence code; changing the main
dataset files alone had not removed the old supporting-artifact path.

These checks complemented the repository's automated tests and static checks.
The [devlog](docs/devlog/) records individual changes and verification results;
[FINDINGS.md](FINDINGS.md) provides reproducible data investigations. My manual
checks above are not a claim that every release or production-capacity gate is
complete.
