# ADR-0018: Use Amazon Cognito for login and OAuth2 token issuance

Status: **Accepted**

Date: 2026-10-01

Resolves authorization-server ownership and provider selection left open in
ADR-0017. Preserves application-owned authorization in ADR-0016.

## Context

The user selected Cognito after discussing the responsibilities of an OAuth2
authorization server, client and resource server. The application already
targets AWS, uses seeded personas and keeps permissions in SQLite. A managed
service reduces credential, login and token-issuer implementation work.

## Options considered

| Option | Benefit | Cost |
| --- | --- | --- |
| Amazon Cognito User Pools | Managed credentials, login and OAuth2 token issuance in AWS | Cloud configuration and login dependency |
| Self-hosted identity service | Control over the provider deployment | Additional service operation and maintenance |
| In-house authorization server | Full implementation control | More protocol, credential and security lifecycle work |

## Decision

- Use Amazon Cognito **User Pools** as the managed user directory and OAuth2
  authorization server. Use its hosted login and Authorization Code with PKCE
  for the user flow discussed with the user.
- Provision the three challenge login accounts in Cognito; disable public
  self-registration. Keep local persona, identity mapping and authorization
  records in SQLite. Password verification and credential storage belong
  to Cognito, not a duplicate application password store.
- FastAPI serves as the protected resource server. Validate Cognito access
  tokens with a maintained library: signature/allowed algorithm, expected
  issuer, expiry, token purpose and intended app client/resource as applicable.
  Handle signing-key caching/rotation; untrusted tokens cannot choose arbitrary
  issuers or key endpoints. Bind verified issuer and `sub` to the local user.
- Our own tables determine roles, permissions and applicable row/column rules.
  Cognito groups and OAuth scopes do not independently grant product data
  access. Unknown/unassigned local users receive no product permissions.
- OIDC is still not required under ADR-0017. Cognito's OIDC capabilities do
  not require the product to request or accept ID tokens for API access.
- Cognito Identity Pools and direct user AWS credentials are unnecessary for
  this setup: the trusted backend accesses S3 on users' behalf.

## Consequences and remaining design

Configure the user pool, app client, domain, allowed callbacks/logout URLs,
OAuth scopes and seeded account provisioning reproducibly. Local development
needs a documented Cognito login configuration; mocked tests do not establish
that the deployed integration works. A new login depends on Cognito availability.

Preserve accepted one-hour application sessions, no automatic renewal initially,
independent sessions and current-session invalidation on logout. Client/backend
ownership of code exchange, token-to-session binding and revocation enforcement
remain to be designed. Signature/expiry-only JWT checks do not enforce Cognito
revocation by themselves; do not claim logout is complete without testing the
application's current-session invalidation.

Authlib remains the recommended integration package, not an installed or pinned
dependency. AWS region, concrete identifiers and exact client configuration
remain open. No infrastructure has been provisioned by this decision.

## References

- [Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html)
- [OAuth2 grants and PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/federation-endpoints-oauth-grants.html)
- [Access-token verification](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html)
- [Token revocation](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html)
