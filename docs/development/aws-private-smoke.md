# Private EC2 smoke environment

This is the October 13, 2026 **private smoke** deployment accepted in
[ADR-0093](../adr/0093-private-ec2-analytical-smoke.md). It is running in AWS
account `381999184392`, region `us-east-2`, using profile
`outage-explorer-new`. It reuses the existing RDS, Cognito and S3 resources.
This guide records the original private smoke configuration. ADR-0094 later
added a backend-only public HTTPS endpoint and disabled the EC2 web service.
Use the public backend guide for the current ingress and auth settings.

## Current host

- EC2 `i-002cf2915a26090f7`, Amazon Linux 2023, `t3.small`, encrypted
  30 GiB gp3 root. Instance role and security group allow only required
  outbound access; the security group has no inbound rules.
- Backend checkout `/opt/outage-explorer`, branch `refactor/backend`;
  frontend checkout `/opt/outage-explorer-web`, branch `main`.
- `outage-api.service` and `outage-web.service` are enabled and bind only
  `127.0.0.1:8000` and `127.0.0.1:3000`. The API uses the explicit reviewed
  analytical and SQL parser startup path as UID 65534 with Docker socket group
  access. Its systemd override is
  `/etc/systemd/system/outage-api.service.d/analytical.conf`.
- `/opt/outage-smoke-start.py` retrieves backend environment values from the
  encrypted SSM parameter `/outage-explorer/smoke/backend-env`, then starts the
  analytical HTTP entry point. Do not copy decrypted values into this repository.
- Reviewed nonsecret profiles are under `/var/lib/outage-runtime-smoke/` as
  `runtime-reviewed.json` and `parser-reviewed.json`. Matching native reports,
  parser log and representative workload report are retained there. The worker
  image is pinned by the runtime profile; changing it or its host profile needs
  fresh matching evidence and review.
- The independently supervised refresh worker is **idle**. No refresh or
  publication was part of this smoke test.

## Connect from the Mac

Use two terminals. The Session Manager plugin is installed in the local
ignored `.local-runtime/bin` directory; include that directory in `PATH` if
the `session-manager-plugin` command is not found.

```sh
aws ssm start-session --profile outage-explorer-new --region us-east-2 \
  --target i-002cf2915a26090f7 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3000"],"localPortNumber":["3000"]}'
```

```sh
aws ssm start-session --profile outage-explorer-new --region us-east-2 \
  --target i-002cf2915a26090f7 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

Open `http://localhost:3000/sign-in`. Both tunnels are needed because the
browser and web server use the API at `http://localhost:8000`.

For a host shell, run `aws ssm start-session --profile outage-explorer-new
--region us-east-2 --target i-002cf2915a26090f7`. From that shell, inspect
`sudo systemctl status outage-api outage-web` and
`sudo journalctl -u outage-api -n 80 --no-pager` without printing the SSM
parameter value. The private health endpoint is `http://localhost:8000/health`.

## Acceptance and limits

The user confirmed sign-in, a dataset preview and `SELECT 1` through the
tunnels. Host logs returned HTTP 200 for authenticated preview and query;
unauthenticated catalog and preview returned 401, and query submission without
CSRF returned 403. The native isolation and parser checks passed, and the
representative analytical-only workload sampled all 33 containers. The
initial 512 MiB container, 128 MiB engine, 16 MiB spill and 10-second query
limits are containment settings, not production sizing.

The host is billed while running. Full high-water and cold-cache performance,
refresh/API overlap, production service topology and public ingress/TLS remain
open. This environment cannot serve the deployed Vercel frontend through its
private localhost tunnel.
