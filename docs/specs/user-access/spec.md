# Spec: Seeded users, login, and role access

> Status: draft · Slug: user-access

## Problem

Seeded Viewer, Analyst, and Admin users need to sign in and receive only the
access their assigned role permits. This effort can progress independently
while the unfinished connector blocks other product modules.

## Goal

Seeded users can sign in by email, identify their single role, and use a fixed-duration session whose access ends on expiry or logout.

## Requirements

### Functional (EARS)

- **FR1:** THE SYSTEM SHALL establish the initial users through seeding with one account for each Viewer, Analyst, and Admin persona.
- **FR2:** WHEN a seeded user completes valid email-based login THE SYSTEM SHALL establish an authenticated application session for that user.
- **FR3:** THE SYSTEM SHALL assign exactly one role, Viewer, Analyst, or Admin, to each seeded user.
- **FR4:** WHEN a signed-in user requests their current identity THE SYSTEM SHALL expose their assigned role.
- **FR5:** IF an identity lacks a recognized seeded user or valid assigned role THEN THE SYSTEM SHALL deny product access.
- **FR6:** WHEN determining a user's access THE SYSTEM SHALL use the trusted application-owned role assignment.
- **FR7:** WHILE a valid session belongs to a Viewer THE SYSTEM SHALL limit analytical access to national datasets.
- **FR8:** WHILE a valid session belongs to an Analyst or Admin THE SYSTEM SHALL permit access to all analytical datasets.
- **FR9:** WHEN a user with a valid Admin session requests refresh initiation THE SYSTEM SHALL authorize that operation.
- **FR10:** WHEN a user with a valid Admin session requests protected refresh outcomes or diagnostics THE SYSTEM SHALL authorize that operation.
- **FR11:** IF a caller lacks a valid Admin session THEN THE SYSTEM SHALL deny refresh initiation and protected refresh outcome or diagnostic access.
- **FR12:** WHEN any protected operation is requested THE SYSTEM SHALL check session validity and role access before protected data access or execution, including direct requests and subsequent browsing or result pages.
- **FR13:** WHEN a successful login establishes an application session THE SYSTEM SHALL set its expiry to one hour after establishment by default.
- **FR14:** WHILE an application session exists THE SYSTEM SHALL preserve its original expiry regardless of activity or browser reopening.
- **FR15:** WHEN a user reopens the browser before their session expires THE SYSTEM SHALL preserve sign-in if that session remains valid and has not been logged out.
- **FR16:** IF an application session has expired THEN THE SYSTEM SHALL require a new sign-in before allowing further protected access through that session.
- **FR17:** WHEN a user logs out THE SYSTEM SHALL invalidate the current application session.
- **FR18:** WHEN a user logs out of one session THE SYSTEM SHALL preserve other independently established sessions.
- **FR19:** IF login details are invalid THEN THE SYSTEM SHALL return a generic login failure.
- **FR20:** IF access is denied THEN THE SYSTEM SHALL exclude protected data from the failure response.

### Technical / Non-functional

- **TR1:** Local user information is limited to essential identity/login linkage and the assigned role; credential storage and verification remain with the existing managed identity provider.
- **TR2:** Identity must be verified against the trusted provider before binding it to a seeded user; caller-supplied roles and provider groups or scopes cannot independently grant application access.
- **TR3:** Automatic token renewal is excluded; no renewal may extend the application session.
- **TR4:** Login, session lifecycle, and role policy must be verifiable independently of connector completion or analytical data availability.

## Inputs & Outputs

- Inputs: seeded user identities and single-role assignments; email address and login credentials; verified login identity; current session; requested protected operation and, where applicable, analytical datasets.
- Outputs: login success or generic failure; authenticated identity and assigned role; fixed session expiry; authorization or denial; current-session logout outcome.
- Contracts touched: user sign-in/sign-out, current identity, and access checks for catalog, preview, SQL execution/result pages, and refresh initiation/outcomes.
- Exact identity fields, transport shapes, provisioning mechanics, and session integration are subsequent design decisions; this specification selects no additional profile fields or credential values.

## Scope

### In scope

- Seeded users and roles, email login, trusted identity binding, and single-role access.
- One-hour sessions by default, browser reopening within a valid session, expiry, and current-session logout with independent concurrent sessions.
- Access decisions for downstream data and refresh features when those features are delivered.

### Out of scope (non-goals)

- Registration or Admin user administration, including backend operations and screens, throughout this implementation.
- Multiple roles per user, individual grants, per-role read/write/delete permission catalogs, attribute-based rules, and row/column policies.
- Automatic renewal, extended sign-in, and special continuity or recovery across backend restarts/outages; signing in again may be necessary.
- Password-recovery screens, additional profile data, and a separate credential system.
- Implementing analytical data features, refresh execution, or the separate UI client.

## Assumptions

- The [requirements brief](requirements.md), [seeded role-only access decision](../../adr/0043-seeded-users-and-role-only-access.md), [single-role decision](../../adr/0044-one-role-per-user.md), and [basic session decision](../../adr/0045-basic-login-session-scope.md) define the agreed scope.
- Initial accounts are planned; existing provider setup does not establish that account provisioning or local identity linkage is complete.
- Analytical access means product analytical datasets; it does not grant access to identity/session records or execution internals.

## Acceptance Criteria

- [x] **AC1:** Initial seeding establishes one account for each of the three personas. (verifies FR1)
- [ ] **AC2:** Each seeded persona can complete email-based login and obtain an authenticated application session. (verifies FR2)
- [x] **AC3:** Every seeded user has exactly one recognized role; more than one user may share a role. (verifies FR3)
- [ ] **AC4:** A signed-in user can obtain their assigned role with their current identity. (verifies FR4)
- [x] **AC5:** Unknown identities and identities without a valid assigned role receive no product access. (verifies FR5)
- [x] **AC6:** Claiming another role or supplying provider groups/scopes does not override the application's assigned role. (verifies FR6, TR2)
- [x] **AC7:** A valid Viewer session permits national analytical access and denies facility/generator analytical access. (verifies FR7)
- [x] **AC8:** Valid Analyst and Admin sessions permit national, facility, and generator analytical access. (verifies FR8)
- [x] **AC9:** A valid Admin session passes the refresh-initiation access check. (verifies FR9)
- [x] **AC10:** A valid Admin session passes protected refresh outcome and diagnostic access checks. (verifies FR10)
- [x] **AC11:** Viewer, Analyst, and callers without valid sessions are denied refresh initiation and protected refresh outcomes/diagnostics. (verifies FR11)
- [x] **AC12:** Direct protected requests and later browsing/result pages cannot bypass session and role checks; denied requests perform no protected data access or execution. (verifies FR12)
- [ ] **AC13:** A newly established session has a default expiry exactly one hour after establishment. (verifies FR13)
- [ ] **AC14:** Activity and browser reopening do not change the original session expiry, and no automatic token renewal occurs. (verifies FR14, TR3)
- [ ] **AC15:** Closing and reopening the browser within the valid hour preserves sign-in unless that session has been logged out or otherwise invalidated. (verifies FR15)
- [ ] **AC16:** At or after expiry, the old session cannot access protected operations; a new sign-in is required. (verifies FR16)
- [ ] **AC17:** After logout, reuse of the logged-out session is denied. (verifies FR17)
- [ ] **AC18:** Logging out of one independently signed-in session leaves another valid independent session usable. (verifies FR18)
- [ ] **AC19:** Invalid login details return a generic failure without revealing whether the user exists. (verifies FR19)
- [x] **AC20:** Access-denial responses contain no protected data. (verifies FR20)
- [x] **AC21:** Local user information contains only essential identity/login linkage and one role, without a duplicate credential store. (verifies TR1)
- [x] **AC22:** Login, session lifecycle, and role-policy verification can complete without a finished connector or available analytical data. (verifies TR4)

## Open Clarifications

_None._


## Verification status — 2026-10-05

Checked criteria have controlled implementation evidence and/or read-only live
seed/schema evidence in [verification.md](verification.md). AC2, AC4 and AC13–AC19
retain unchecked overall acceptance because their required real managed-login or
browser portions were explicitly deferred. Controlled tests verify those behaviors
(including actual persistent Chromium reopening), but do not substitute for live
email login, first-password completion or managed-login credential presentation.
The verification matrix reconciles every criterion; downstream analytical/refresh
feature implementations remain responsible for their own fresh authorization,
reference extraction and result ownership. T5.14/T5.C and overall Phase 5 remain open.
