#!/bin/bash

set -eu

cd /root

# Download to a unique filename, to avoid collisions with any existing file
INSTALLER=$(mktemp /root/yd-agent-installer-XXXXXXXX.sh)
trap 'rm -f "$INSTALLER"' EXIT

echo "Downloading the Agent installer script"
curl -fLsS -o "$INSTALLER" \
  https://raw.githubusercontent.com/yellowdog/resources/refs/heads/main/agent-install/linux/yd-agent-installer.sh

# Install/update the Agent and restart the Agent service
bash "$INSTALLER"
