#!/bin/sh
set -eu
# Run only on the dedicated Linux daemon host (native or VM), never on macOS.
test "$(uname -s)" = Linux
test ! -e /var/lib/outage-analytical/spill.img
test ! -e /opt/outage-runtime-validation
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip e2fsprogs util-linux
sudo install -d -m 0711 /var/lib/outage-analytical
sudo install -d -m 0700 /var/lib/outage-analytical/spill
sudo install -m 0600 /dev/null /var/lib/outage-analytical/spill.img
sudo fallocate -l 16777216 /var/lib/outage-analytical/spill.img
sudo mkfs.ext4 -F -m 0 -N 1024 -O ^has_journal /var/lib/outage-analytical/spill.img
sudo mount -o loop,rw,noexec,nosuid,nodev /var/lib/outage-analytical/spill.img /var/lib/outage-analytical/spill
sudo rmdir /var/lib/outage-analytical/spill/lost+found
sudo chown 65534:65534 /var/lib/outage-analytical/spill
sudo chmod 0700 /var/lib/outage-analytical/spill
sudo install -d -m 0755 /opt/outage-runtime-validation
sudo install -d -o 65534 -g 65534 -m 0700 /var/lib/outage-runtime-validation
# The trusted controller gets daemon access through a supplementary group.
# The isolated worker receives no daemon socket or host group grants.
test -S /run/docker.sock
stat -c 'socket mode=%a owner=%u group=%g' /run/docker.sock
uname -srm
python3 --version
docker info --format '{{.ServerVersion}} {{.OSType}} {{.Architecture}} {{.Name}}'
