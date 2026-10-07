# Reproducible local machine setup

Status: implementation authorized by user, October 7, 2026.

Provide a guided setup for the existing local architecture, including Docker,
without relying on another contributor's private startup scripts or temporary
files. Native Ubuntu is the common runtime; other operating systems can use an
Ubuntu VM. Apple Silicon can use the existing dedicated Colima guest.

- Document installation, cloning both repositories, external resource/account
  prerequisites, configuration, worker build, candidate identities, actual-host
  review, application startup, port forwarding, shutdown and reboot recovery.
- Deliver the API guest entry point and a manual configuration command. Transfer
  secrets only through stdin into private files; keep them out of command arguments,
  images, source archives and analytical/parser workers.
- Preserve reviewed profile/parser gates, UID/GID 65534, dynamic Docker socket
  group, one API owner/analytical slot and independent refresh supervision.
- Support native Linux configuration/credential renewal as well as Colima. Do
  not require a private `/tmp` script, hard-coded host architecture or group 991.
- Generate parser executable hashes and worker platform from the actual host.
- Setup must not migrate, seed, retrieve EIA, publish, start refresh or activate
  the API implicitly. Configuration and explicit run remain separate commands.
- Report controlled checks separately from a fresh-machine/live rehearsal. User
  acceptance of the existing application remains complete.

No persistence, deployment or authorization boundary changes are selected.
