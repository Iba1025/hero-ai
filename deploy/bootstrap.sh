#!/usr/bin/env bash
# Hero.AI droplet bootstrap (Phase 6, DEC-27) — Ubuntu 24.04, DO TOR1.
# Run ONCE as root, BEFORE any application bytes land on the box.
#
#   scp deploy/bootstrap.sh root@<ip>:/root/ && ssh root@<ip> 'bash /root/bootstrap.sh'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "── 1/5 firewall FIRST (DEC-27: 80/443/SSH only) ──────────────────────"
apt-get update -q
apt-get install -yq ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
# NOTE: Docker's iptables rules BYPASS ufw for published container ports.
# The lean compose file (DEC-29/30) publishes only caddy 80/443 (public by
# design). Publishing any other port in docker-compose.yml would silently
# punch through this firewall: don't.

echo "── 2/5 basic hardening ───────────────────────────────────────────────"
apt-get install -yq unattended-upgrades fail2ban
systemctl enable --now fail2ban

echo "── 3/5 Docker Engine + compose plugin (official apt repo) ────────────"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker --version && docker compose version

echo "── 4/5 uv (host-side: invariant suite via testcontainers) ────────────"
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "── 5/5 app directory ─────────────────────────────────────────────────"
mkdir -p /opt/hero/data/manuals

echo "bootstrap complete — rsync the repo to /opt/hero next (deploy/push.sh)"
