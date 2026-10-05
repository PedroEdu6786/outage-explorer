# ADR-0044: Assign exactly one role per user

Status: **Accepted by user direction**

Date: 2026-10-04

Resolves role cardinality left open in ADR-0043.

## Context and decision

The user specified that each user has just one role. Each seeded application
user must have exactly one assigned role: Viewer, Analyst, or Admin.
A role can be shared by multiple users. Multiple roles per user and role
combination rules are outside scope.

Preserve seeded users, no registration or Admin user management, Cognito-owned
credentials, and application-owned role-only access under ADR-0043. An identity
without a valid local user and assigned role receives no product access.

## Alternatives and consequences

Multiple roles would require assignment and combination semantics that the
user does not need. One role per user keeps access decisions unambiguous.
The subsequent table design must enforce exactly one valid role for every
local user; this decision does not create a schema, migration, or seeded data.
