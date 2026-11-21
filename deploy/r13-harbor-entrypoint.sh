#!/bin/sh
set -eu

# Keep the socket, state and child storage inside the runner container.
exec dockerd \
  --host unix:///tmp/autoeval-docker.sock \
  --data-root /var/lib/autoeval-private-docker \
  --exec-root /tmp/autoeval-private-docker-exec \
  --pidfile /tmp/autoeval-private-docker.pid \
  --storage-driver vfs \
  --iptables=false \
  --ip6tables=false
