# ADR-0094: Expose only the EC2 backend through CloudFront

Status: **Accepted by explicit user direction**

Date: 2026-10-13

## Context

ADR-0093 activated preview and SQL for a private EC2 smoke test. The user then
requested a publicly available deployment and chose an AWS HTTPS URL. The first
CloudFront configuration also exposed the EC2 frontend. The user clarified that
this deployment is **backend only**; the existing Vercel frontend is separate.

## Decision

- Keep one CloudFront HTTPS distribution with a VPC origin to the existing EC2
  instance. Its service-managed security group is the only source allowed to
  reach EC2 port 80. Nginx proxies `/api/` and `/health` to the backend on
  `127.0.0.1:8000`; other paths return 404. Disable the EC2 frontend service.
- Use the existing Vercel origin for browser login callback and UI redirects.
  Cognito allows that callback; the backend's configured public, UI and callback
  origins match it. Vercel's separate `/api` rewrite must target the public API
  before browser login can be considered integrated. This decision does not
  authorize an AWS frontend deployment or a Vercel deployment.
- Serve the public backend with one Waitress process, four threads and bounded
  connections, request headers and bodies. Keep the listener on loopback and
  retain the reviewed analytical runtime, isolated workers and idle refresh.

## Consequences and open evidence

CloudFront is the public API address; it does not host application pages. The
instance remains a single `t3.small` smoke host. The scoped analytical evidence
from ADR-0093 still applies, but full high-water/spill, S3 performance,
simultaneous refresh/API capacity, browser integration and production availability
are not established by this deployment. No refresh or publication is authorized.
