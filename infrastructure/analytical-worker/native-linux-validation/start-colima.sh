#!/bin/sh
set -eu
# Dedicated synthetic analytical validation VM; keep Desktop/default unchanged.
exec colima start --profile outage-runtime --runtime docker --arch aarch64 \
  --vm-type vz --cpus 4 --memory 6 --disk 20 --root-disk 20 \
  --activate=false --ssh-config=false --ssh-agent=false --mount none \
  --template=false --port-forwarder=none --binfmt=false
