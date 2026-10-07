# Implementation plan

1. Reuse existing Linux provisioning/image helpers and public analytical startup.
   Pin guest installation to the repository dependency lock, include helper scripts
   in the source archive and discover the actual worker/parser identities.
2. Extend the existing operator launcher with explicit configuration through the
   dedicated Colima transport. Install a checked-in entry point plus private settings, CA and
   reviewed JSON through an in-memory archive. Discover the Docker socket group.
3. Write a numbered guide with one required Apple Silicon/Colima path, exact
   configuration examples, review steps and lifecycle/troubleshooting checkpoints.
4. Verify configuration transport, secret handling, startup environment and command
   behavior with controlled tests; run relevant existing checks. Do not provision
   or change the user's running services to validate documentation.

Make-driven follow-up: a standard-library host orchestrator sequences existing
helpers and sends bounded controller commands through stdin. Expose each stage
with Make; preserve fresh-resource guards and explicit report/review/run steps.
