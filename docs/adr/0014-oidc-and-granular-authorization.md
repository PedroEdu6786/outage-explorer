# ADR-0014: Require OAuth2/OIDC and granular authorization

Status: **Accepted requirements; provider and detailed policy design open**

Date: 2026-10-01

## Context and decision

The user accepted the proposed authentication experience and explicitly added
OAuth2/OIDC and granular authorization (RBAC/ABAC, column or row level).
This replaces the draft's exclusion of identity-provider integration and
its assumption that local password verification alone completes authentication.

Retain the accepted user experience: configurable one-hour application session,
re-login on expiry, no automatic renewal initially, independent concurrent
sessions and logout invalidating the current application session. Invalid
credentials produce a generic failure. Provider SSO sessions, provider token
lifetimes and application sessions are distinct; their mapping is still open.

Use OIDC for user authentication and OAuth2 for delegated API authorization.
Authorization Code with PKCE is the recommended flow; select the provider,
client type and callback setup before finalizing endpoints. Do not implement
the resource-owner-password grant or label a custom bearer-token login OIDC.
An opaque application session after OIDC login remains an option; direct
provider access tokens are another option. Do not use an ID token as an API
access token. Current-session logout must actually stop access through that
session; deleting a client token alone is insufficient.

## Granular access requirements

- Retain Viewer national-only, Analyst/Admin all analytical datasets and
  Admin-only refresh as the baseline role policy.
- Design one server-side authorization policy path using trusted identity,
  role and applicable attributes; never accept client-supplied roles or
  filters as authorization evidence.
- Resolve concrete row/column restrictions with the user and data model.
  No tenant, facility assignment or hidden-column rule is invented here.
  Existing dataset-level RBAC alone is not proof of row/column enforcement.
- Apply configured policies to catalog schemas, previews, metrics, every
  SQL reference and expression, pagination and diagnostics. Reauthorize
  each request. SQL joins, subqueries, aggregates, filters and ordering
  must not provide bypasses.
- If row/column restrictions apply, whole-file dataset authorization is
  insufficient when files contain forbidden data. Revisit worker inputs
  and authorized relations so raw backing files cannot bypass the policy.
  Enforcement mechanism and adversarial validation remain design work.

## Alternatives and consequences

The earlier local-password-only design is simpler but does not meet the new
protocol requirement. OAuth scopes do not by themselves enforce row/column
rules in DuckDB. Keep seeded challenge personas and local operational identity
records; provision/link their provider identities once the provider is selected,
using verified issuer and subject rather than untrusted profile fields.

Provider, local development login setup, account provisioning, claim mapping,
session/token validation and revocation implementation remain open. Frontend
product work remains deferred; an identity provider's login page is not a
request to build the deferred application UI. No provider was provisioned.

## References

- [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html)
- [OAuth security best practices](https://www.rfc-editor.org/info/rfc9700/)
