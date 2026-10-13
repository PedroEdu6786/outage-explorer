# Recover an existing local installation

[Daily development](local-setup.md) · [First-time setup](fresh-machine.md) ·
[Make commands](local-commands.md)

Use this checklist after restarting the dedicated `outage-runtime` Colima VM,
when `make local-configure` fails, or when the API reports
`pool-1: PostgreSQL connection failed`. Run commands from the backend checkout
on macOS unless a step says otherwise. This is for an **existing reviewed
installation**; `make local-runtime` is a fresh-install command and refuses
existing resources.

## Restore the VM after a reboot

Start the existing profile and check its spill filesystem:

```sh
colima start --profile outage-runtime
colima ssh --profile outage-runtime -- mountpoint /var/lib/outage-analytical/spill
```

If the second command says `is not a mountpoint`, restore the existing spill
image, then check again:

```sh
colima ssh --profile outage-runtime -- sudo mount -o loop,rw,noexec,nosuid,nodev /var/lib/outage-analytical/spill.img /var/lib/outage-analytical/spill
colima ssh --profile outage-runtime -- mountpoint /var/lib/outage-analytical/spill
```

Stop if the image or mount fails; do not create a replacement image over the
reviewed runtime. `/run/outage-api` is transient and must be reinstalled with
`make local-configure` after a guest reboot. Do not start the API until that
command succeeds.

## `make local-configure` fails

The setup helper suppresses private diagnostics, so check these in order:

1. The API must be stopped. Stop its supervisor with Ctrl+C, or run
   `make stop-analytical` from another backend terminal.
2. Confirm the spill mount using the preceding commands.
3. Confirm that the guest still has reviewed profiles. If it does not, use
   [same-installation profile recovery](#reviewed-profiles-are-missing).
4. Check that the `sslrootcert` path **inside the active database DSN** names
   a readable file on the Mac. `make local-ca` downloads the public RDS CA
   bundle to `.local-runtime/rds-ca.pem`, but it does not change `.env`.
   For a password-mode connection to an RDS PostgreSQL endpoint using
   `sslmode=verify-full`, set the DSN's `sslrootcert` to the downloaded file's
   absolute path. `make local-configure` copies that file into the VM and
   rewrites the guest path. Leave the DSN password private.
5. Retry `make local-configure` before `make run-analytical`.

`AWS_PROFILE` selects the AWS credentials used by the API for AWS resources;
it is separate from the PostgreSQL `user` and password in
`OUTAGE_ACCESS_DATABASE_DSN`. Use the profile configured in your `.env`, not
the example profile name in the first-time walkthrough. An RDS endpoint is a
PostgreSQL server hosted by AWS: `OUTAGE_ACCESS_DATABASE_MODE=password` selects
PostgreSQL password authentication even when the host is RDS.

### Reviewed profiles are missing

After a reboot, `/run/outage-api/runtime.json` and `parser.json` disappear.
`make local-configure` normally retrieves reviewed profiles from
`/var/lib/outage-runtime-validation/`. Check for both files without displaying
their contents:

```sh
colima ssh --profile outage-runtime -- sudo ls -l /var/lib/outage-runtime-validation/runtime-reviewed.json /var/lib/outage-runtime-validation/parser-reviewed.json
```

If those guest files are missing but **this same installation** still has
`.local-runtime/runtime-reviewed.json` and `parser-reviewed.json`, and its
Docker image, parser and filesystem identities have not changed, restore the
private copies:

```sh
colima ssh --profile outage-runtime -- sudo tee /var/lib/outage-runtime-validation/runtime-reviewed.json < .local-runtime/runtime-reviewed.json > /dev/null
colima ssh --profile outage-runtime -- sudo tee /var/lib/outage-runtime-validation/parser-reviewed.json < .local-runtime/parser-reviewed.json > /dev/null
colima ssh --profile outage-runtime -- sudo chmod 600 /var/lib/outage-runtime-validation/runtime-reviewed.json /var/lib/outage-runtime-validation/parser-reviewed.json
make local-configure
```

These commands restore existing reviewed files; they do not create new review
evidence. If the files came from another VM, their origin is uncertain, or an
identity changed, preserve the old evidence and follow the
[runtime recovery procedure](../../infrastructure/analytical-worker/README.md)
to capture and review this VM's current identities. Do not edit review JSON to
make it pass.

## PostgreSQL pool connection fails

`pool-1: PostgreSQL connection failed` is intentionally generic; it does not
identify whether DNS, network access, TLS or credentials failed. First verify
that the active `.env` names the intended PostgreSQL endpoint and database.
The API uses the **installed** settings in `/run/outage-api`, so after changing
`.env`, stop the API, run `make local-configure`, then restart it.

For a remote PostgreSQL endpoint, check reachability **from Colima**, where the
API runs. Replace `DB_ENDPOINT` with the host from your database DSN:

```sh
colima ssh --profile outage-runtime -- getent hosts DB_ENDPOINT
colima ssh --profile outage-runtime -- timeout 7 bash -c 'exec 3<>/dev/tcp/DB_ENDPOINT/5432'
```

The TCP command exits successfully without output if the port is reachable.
If DNS works but TCP times out, check the database's status, routing/VPN and
inbound rules. For a publicly reachable AWS-hosted PostgreSQL instance, compare
the current outbound IPs with the source allowed on its security group's
inbound **TCP 5432** rule:

```sh
curl --fail https://checkip.amazonaws.com
colima ssh --profile outage-runtime -- curl --fail https://checkip.amazonaws.com
```

An earlier `/32` rule may no longer match after the public IP changes. The
environment owner should update the inbound source to the current allowed
developer IP or VPN range; this checklist does not change AWS rules. If the
database is private, an inbound rule alone does not provide a route to it.
Once TCP succeeds, retry login. A remaining failure needs a separate TLS CA,
hostname or PostgreSQL credential check; do not change inbound rules to fix a
certificate or password error.
