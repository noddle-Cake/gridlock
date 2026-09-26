#!/usr/bin/env bash
# One-time setup for a fresh AWS Lightsail Ubuntu 22.04/24.04 instance (2 GB plan or larger).
# Run it on the instance as the default "ubuntu" user:
#   curl -fsSL https://raw.githubusercontent.com/noddle-Cake/gridlock/master/deploy/lightsail-setup.sh | bash
# After this, deploys come from CI (.github/workflows/ci-cd.yml): it copies deploy/ to
# ~/gridlock, loads the image and runs remote-deploy.sh over SSH.
set -euo pipefail

# Docker Engine + compose plugin (official convenience script).
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

# 2 GB swap: Postgres plus the app can OOM a small instance without it.
if ! sudo swapon --show | grep -q '^/swapfile'; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

mkdir -p "$HOME/gridlock"
cat <<'MSG'
Done. Next:
  1. Log out and back in (docker group).
  2. Append the CI deploy public key to ~/.ssh/authorized_keys.
  3. Set repo secrets DEPLOY_HOST, DEPLOY_SSH_KEY, POSTGRES_PASSWORD, GEMINI_API_KEY,
     then push to master (or re-run the CI/CD workflow).
Open TCP 22, 80 and 443 in the Lightsail console (Networking tab).
MSG
