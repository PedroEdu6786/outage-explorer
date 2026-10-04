# ADR-0039: Prepare a separate UI client with atomic components

Status: **Accepted user direction; client implementation pending**

Date: 2026-10-04

## Context

The user requested context for Astra to build the Outage Explorer web client
in another repository. Earlier scope deferred frontend implementation in this
backend repository. The user now selected the client stack, identified an
existing Figma design and specified a reusable component hierarchy.

## Decision

- Keep UI implementation in a separate repository using React, Next.js,
  TypeScript and Tailwind CSS. This repository continues to own the connector,
  analytical model and Flask backend.
- Use the existing Figma design for implementation. Its contents and URL were
  not provided for this context-preparation task.
- Organize the UI with atoms (small reusable primitives), molecules (simple
  compositions without domain logic), organisms (contextual compositions that
  can contain data, status and cohesive UI logic), reusable templates and thin
  pages that render the intended experience.
- Prepare a portable prompt and Markdown context pack describing product
  expectations, exclusions, accepted behavior and pending integration contracts.
  This task does not implement or deploy the client.

## Consequences and open choices

The separate client does not change the backend's layered monolith, data
ownership, authorization or isolated SQL execution boundaries. Historical
frontend deferral remains applicable to implementation inside this repository;
the new direction allows a documented handoff for work in another repository.

The [UI handoff](../context/ui-client/README.md) recommends component/feature
boundaries and an App Router layout. Those details, exact package versions,
hosting, API routes and session transport remain implementation proposals or
open integration choices. No Admin screen or additional product feature is
implicitly selected. Figma inspection and real backend integration remain
necessary before claiming either visual fidelity or end-to-end behavior.

## Alternatives

- Keeping frontend work entirely deferred would not meet the new request for
  an actionable cross-repository handoff.
- Adding React code to the backend repository would conflict with the user's
  explicit separate-repository direction.
- A single unstructured prompt would be easy to paste but harder to maintain;
  a short prompt plus focused context documents preserves the important
  behavioral distinctions without copying the backend's full history.
