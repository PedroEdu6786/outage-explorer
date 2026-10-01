# ADR-0017: Retain OAuth2 without requiring OIDC

Status: **Accepted**

Date: 2026-10-01

Supersedes the mandatory OIDC requirement in ADR-0014 and the OIDC-specific
identity assumptions in ADR-0016. Other accepted behavior remains in force.

## Context and decision

After discussing OIDC prerequisites, the user clarified that OIDC is not needed
and OAuth2 is sufficient. Require OAuth2 access-token authorization without
requiring OIDC login, ID tokens, discovery or a separate OIDC provider.

Keep seeded personas, the configurable one-hour application-session experience,
re-login on expiry, no automatic renewal initially, independent sessions and
current-session invalidation on logout. Our own SQLite authorization tables
remain authoritative for roles, permissions and applicable policy attributes.
Dataset browsing defaults remain accepted in ADR-0015.

## Alternatives and consequences

OIDC offers standardized identity assertions but is not required for the user's
chosen scope. OAuth2 defines access delegation and token issuance/validation;
it does not by itself define how the authorization server authenticates users.
An external provider is not inherently required: authorization-server and
resource-server roles can share a deployment, but their implementation must
still be specified. No in-house authorization server is selected by this ADR.

User sign-in, authorization-server ownership, client/grant flow, local user
binding and token/session validation/revocation remain design choices. A
custom login returning a bearer token is not automatically an OAuth2 protocol
implementation. Do not adopt the resource-owner-password grant; use current
OAuth security guidance. Authorization Code with PKCE remains a candidate.

Authlib remains a package recommendation, not a selected or installed dependency.
No implementation or provider provisioning is performed.

## References

- [OAuth2 roles and framework](https://www.rfc-editor.org/rfc/rfc6749.html)
- [OAuth2 security best practices](https://www.rfc-editor.org/info/rfc9700/)
