# Requirements: Users, authentication, and authorization
> Status: draft · Slug: user-access · Date: 2026-10-04

## Problem statement

Outage Explorer needs seeded users to sign in and receive access appropriate to
one assigned role. The sign-in experience should be simple, with no registration,
user administration, or granular permission management.

This effort can progress independently while the unfinished data connector
blocks other modules. Completing login and role behavior does not require
waiting for analytical data delivery or claim those downstream features are ready.

## Target user / context

The initial users are the Viewer, Analyst, and Admin personas, with one seeded
account per persona. Each user signs in with an email address and has exactly
one role. Users may share a role. The accounts are planned; provisioning has
not yet been verified.

## Success criteria

Seeded users can sign in, see their assigned role, and use only the features
and datasets that role permits. Closing and reopening the browser during a
valid session preserves sign-in. Expiry and sign-out stop access through that
session. The module can be verified independently of connector completion.

## Acceptance criteria

- Seeded users can sign in using an email address and their login credentials.
- Each user has exactly one role: Viewer, Analyst, or Admin. Local user
  information is limited to essential login/identity data and the assigned role.
- Viewer can access national analytical data only. Analyst and Admin can access
  all analytical datasets. Only Admin can initiate refresh and inspect its
  protected outcomes. These boundaries apply when those features are delivered.
- Users cannot gain access by claiming a different role. Unrecognized users
  and identities without a valid role receive no product access.
- Access restrictions hold for direct requests and later browsing/result pages,
  as well as the initial request.
- Sign-in lasts a fixed hour by default. Activity does not extend it; after
  expiry users must sign in again. There is no automatic token renewal.
- Closing and reopening the browser before expiry preserves sign-in, provided
  the session remains valid and the user has not signed out.
- Sign-out stops access through the current session. Other independently signed-in
  sessions are unaffected.
- Invalid login details produce a generic failure. Access errors do not disclose
  protected data.
- Accounts and role assignments are established through seeding, without
  registration or Admin user-management features.

## Non-goals

- Registration and Admin user administration, including screens and backend
  operations, throughout this implementation.
- Multiple roles per user, individual grants, separate read/write/delete
  permissions per role, attribute-based rules, and row/column restrictions.
- Automatic token refresh, extended sign-in, and special recovery to preserve
  sign-in across service restarts or outages. Signing in again may be necessary.
- Password-recovery screens, additional profile information beyond essential
  login data, and building a separate credential system.
- Implementing the analytical data features or the separate UI client as part
  of this module. Their login/access integration still needs to agree with it.

## Open questions

_None at the product-scope level._

## Grounding and subsequent design

This brief records the agreed product behavior. Cognito remains responsible
for credentials and login; PostgreSQL stores seeded application users and roles.
Exact fields, seeding mechanics, login integration, and session handling belong
in the subsequent specification/design, rather than expanding product scope.

- [Seeded users and role-only access](../../adr/0043-seeded-users-and-role-only-access.md).
- [Exactly one role per user](../../adr/0044-one-role-per-user.md).
- [Basic login sessions](../../adr/0045-basic-login-session-scope.md).
- [Cognito login](../../adr/0018-cognito-authentication.md).
- [Backend specification](../outage-explorer-backend/spec.md).
- [UI integration context](../../context/ui-client/04-backend-integration.md).
