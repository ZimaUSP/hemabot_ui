#!/usr/bin/env bash
# Removes the Hemabot systemd services installed by setup.sh.
# The configuration in /etc/hemabot is kept unless --purge is given.
set -euo pipefail

readonly SYSTEMD_DIR="${HEMABOT_SYSTEMD_DIR:-/etc/systemd/system}"
readonly CONFIG_DIR="${HEMABOT_CONFIG_DIR:-/etc/hemabot}"
readonly SERVICES=(hemabot-ui hemabot-ros)

purge=0
case "${1:-}" in
  "") ;;
  --purge) purge=1 ;;
  -h | --help) echo "Usage: sudo $0 [--purge]"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 1 ;;
esac

[[ "$(id -u)" == "0" ]] || { echo "run as root: sudo $0" >&2; exit 1; }

for service in "${SERVICES[@]}"; do
  if [[ -f "$SYSTEMD_DIR/$service.service" ]]; then
    echo "Removing $service.service"
    systemctl disable --now "$service.service" || true
    rm -f "$SYSTEMD_DIR/$service.service"
  fi
done
systemctl daemon-reload

if ((purge)); then
  echo "Removing $CONFIG_DIR"
  rm -rf "$CONFIG_DIR"
else
  echo "Configuration kept in $CONFIG_DIR (use --purge to remove it)"
fi
