# ADR-0043: Seed users and authorize by role only

Status: **Accepted by user direction**

Date: 2026-10-04

Supersedes the granular RBAC/ABAC and row/column-policy scope in ADR-0014.
Refines application-owned authorization in ADR-0016; preserves Cognito login
and session behavior in ADR-0017/0018 and PostgreSQL storage in ADR-0032.

## Context

The user specified that users will be seeded for the entire implementation.
There will be no registration and Admins will not manage users. Local user
records need only essential login/identity data and role assignments. Access
is determined by role; separate read/write/delete permissions per role are
not part of the current effort.

## Decision

- Seed application users, roles, and assignments in PostgreSQL. Start with the
  existing Viewer, Analyst, and Admin personas. Account provisioning remains
  pending; an existing Cognito setup does not prove accounts or links exist.
- Include no public registration, Admin user administration, or user-management
  endpoints/screens throughout this implementation. Provisioning is a controlled
  setup operation, not an Admin product capability.
- Keep local user information limited to essential identity/login linkage and
  role assignment. Exact fields and role cardinality remain design questions.
- Cognito continues to own credentials and login. Seeded local users must link
  to provisioned Cognito identities through verified issuer and subject; this
  decision does not introduce local password authentication or storage.
- Application-owned role assignments determine access. Viewer accesses national
  analytical datasets; Analyst/Admin access all analytical datasets; only Admin
  initiates refresh and reads protected refresh diagnostics.
- Do not introduce per-role read/write/delete permission catalogs, individual
  grants, ABAC attributes, or row/column restrictions for the current scope.
  Revisit richer access policy only through an explicit scope change.
- Enforce role policy in application use cases before analytical data access,
  including subsequent pages. Unlinked or unassigned identities have no product
  access. Provider groups/scopes cannot independently confer application access.

## Alternatives and consequences

Admin-managed accounts and granular permission tables add behavior the user
explicitly excluded. Seeded users and role assignments keep the initial model
focused on the three accepted personas. Role-only authorization still requires
consistent checks across all access paths and authorized worker inputs.

Database seeding mechanics, constraints, identity provisioning, and login/session
integration need design and verification. No schema, migrations, provisioning,
or runtime implementation is created by this decision.
