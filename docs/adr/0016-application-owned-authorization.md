# ADR-0016: Own authorization in application tables

Status: **Accepted**

Date: 2026-10-01

## Context and decision

The user clarified that authorization is entirely controlled by our own
authorization tables. This refines ADR-0014's identity/policy boundary.

The OIDC provider establishes identity. Link its verified issuer and subject
to a local operational user. Our SQLite authorization tables are authoritative
for application roles, permissions and any applicable row/column policy
attributes. Provider groups, role claims, email addresses or OAuth scopes
must not independently confer application data permissions.

Authenticate and evaluate current application policy on each protected
request, including pagination and SQL. An authenticated but unassigned identity
receives no application permissions by default. OAuth token validation and
intended-recipient checks remain required when that token type is used;
they do not replace local permission checks.

## Alternatives and consequences

Mapping provider groups directly to data permissions would couple product
policy to provider configuration and contradict the user's requested ownership.
Local tables preserve one application-controlled authority across providers
and all access paths. The existing three persona policies remain the baseline.

This does not select a generic policy engine, an authorization-table schema,
or concrete row/column restrictions. Those still need design grounded in the
data model. Identity provider, OIDC integration package and session mapping
also remain open. No implementation or provider provisioning is performed.
