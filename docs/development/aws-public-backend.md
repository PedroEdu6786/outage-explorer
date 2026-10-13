# Public EC2 backend smoke endpoint

ADR-0094 records the user's backend-only direction. The API is available at
`https://dwtkndoe7o8qk.cloudfront.net`; `/health` is public and `/api/` is
proxied to the EC2 loopback API. `/` and `/sign-in` return 404. The EC2 frontend
service is disabled. The existing Vercel frontend is a separate deployment.

CloudFront distribution `E102BM8FMO3JQ9` uses VPC origin
`vo_6lvIKibiSdCDu3JSkn5ht2` on EC2 `i-002cf2915a26090f7` in `us-east-2`.
The EC2 security group permits port 80 only from the CloudFront service-managed
security group. Nginx proxies to the API's `127.0.0.1:8000` listener. The API
uses one Waitress process; the independent refresh service remains idle.

The backend loads its protected environment from SSM parameter
`/outage-explorer/smoke/backend-env`. Its public/UI origin and Cognito callback
are `https://outage-explorer-web.vercel.app` and
`https://outage-explorer-web.vercel.app/api/auth/callback`. Cognito keeps the
localhost callback for local development. Do not copy parameter values into
logs or repository files.

The Vercel frontend needs `OUTAGE_API_ORIGIN` set to the CloudFront origin and a
separate frontend deployment before its `/api` rewrite will reach this backend.
That integration was not part of the backend deployment. An unauthenticated
`/api/auth/session` response of 401 and a 404 on `/sign-in` verify the API-only
ingress; they do not prove browser login or analytical capacity.

The private smoke runbook remains useful for Session Manager access, runtime
evidence and rollback. The full readiness checkpoints listed in ADR-0093 remain
open; refresh and publication stay idle.
