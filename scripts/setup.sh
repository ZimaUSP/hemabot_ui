#!/usr/bin/env bash
# Hemabot UI setup for the robot's Raspberry Pi (Ubuntu Server 22.04 + ROS 2 Humble).
#
# Installs system packages, creates the Python virtualenv, writes the configuration
# file and installs two systemd services that start on boot:
#   hemabot-ros.service  ROS 2 bringup (ros2 launch minihema_launch minihema_launch.py)
#   hemabot-ui.service   web interface
#
# Safe to run again (e.g. after `git pull`): existing configuration is preserved.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly APP_DIR
# Overridable so the script can be exercised in tests without touching the system.
readonly SYSTEMD_DIR="${HEMABOT_SYSTEMD_DIR:-/etc/systemd/system}"
readonly CONFIG_DIR="${HEMABOT_CONFIG_DIR:-/etc/hemabot}"
readonly ENV_FILE="$CONFIG_DIR/hemabot.env"
readonly ROS_ROOT="${HEMABOT_ROS_ROOT:-/opt/ros}"
readonly SERVICES=(hemabot-ros hemabot-ui)
readonly APT_PACKAGES=(python3-venv python3-pip avahi-daemon)
# Hardware access used by the bringup: serial LiDAR, I2C IMU, GPIO motors, joystick.
readonly HARDWARE_GROUPS=(dialout i2c gpio input video)

service_user="${SUDO_USER:-}"
ros_workspace=""
ros_distro="humble"
port="80"
install_apt=1
start_services=1

usage() {
  cat <<EOF
Usage: sudo $0 [options]

Options:
  --user NAME          user that runs the services (default: the user calling sudo)
  --ros-ws PATH        hemabot_ros2 workspace (default: ~USER/hemabot_ros2)
  --ros-distro NAME    ROS 2 distribution (default: $ros_distro)
  --port N             web interface port (default: $port)
  --skip-apt           do not install system packages
  --no-start           install and enable services without starting them now
  -h, --help           show this help
EOF
}

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() {
  printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
  exit 1
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --user) service_user="${2:?--user needs a value}"; shift 2 ;;
      --ros-ws) ros_workspace="${2:?--ros-ws needs a value}"; shift 2 ;;
      --ros-distro) ros_distro="${2:?--ros-distro needs a value}"; shift 2 ;;
      --port) port="${2:?--port needs a value}"; shift 2 ;;
      --skip-apt) install_apt=0; shift ;;
      --no-start) start_services=0; shift ;;
      -h | --help) usage; exit 0 ;;
      *) usage >&2; die "unknown option: $1" ;;
    esac
  done
  if ! [[ "$port" =~ ^[0-9]+$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
    die "invalid port: $port"
  fi
  port=$((10#$port)) # normalize, e.g. "080" -> "80"
}

require_root() {
  [[ "$(id -u)" == "0" ]] || die "run as root: sudo $0"
}

resolve_user() {
  [[ -n "$service_user" && "$service_user" != "root" ]] ||
    die "could not infer the robot user; pass --user NAME (the services must not run as root)"
  local passwd_entry
  passwd_entry="$(getent passwd "$service_user")" || die "user '$service_user' does not exist"
  service_home="$(cut -d: -f6 <<<"$passwd_entry")"
  ros_workspace="${ros_workspace:-$service_home/hemabot_ros2}"
}

check_ros() {
  local setup_file="$ROS_ROOT/$ros_distro/setup.bash"
  [[ -f "$setup_file" ]] ||
    die "ROS 2 $ros_distro not found ($setup_file). Install it first: see hemabot_ros2/docs/os_installation_raspberry.md"
  if [[ ! -f "$ros_workspace/install/setup.bash" ]]; then
    warn "workspace not built: $ros_workspace/install/setup.bash is missing."
    warn "build it with: cd $ros_workspace && colcon build  (hemabot-ros.service needs it)"
  fi
}

install_system_packages() {
  if ((install_apt == 0)); then
    log "Skipping system packages (--skip-apt)"
    return
  fi
  log "Installing system packages: ${APT_PACKAGES[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${APT_PACKAGES[@]}"
}

grant_hardware_access() {
  local group
  local granted=()
  for group in "${HARDWARE_GROUPS[@]}"; do
    if getent group "$group" >/dev/null; then
      usermod -a -G "$group" "$service_user"
      granted+=("$group")
    fi
  done
  log "User '$service_user' is in hardware groups: ${granted[*]:-none found}"
}

create_virtualenv() {
  local venv="$APP_DIR/.venv"
  log "Creating virtualenv at $venv"
  # --system-site-packages exposes rclpy and the ROS message packages installed by apt.
  run_as_user python3 -m venv --system-site-packages "$venv"
  run_as_user "$venv/bin/python" -m pip install --quiet --upgrade pip
  run_as_user "$venv/bin/python" -m pip install --quiet --editable "$APP_DIR"
}

run_as_user() {
  runuser -u "$service_user" -- "$@"
}

render_template() {
  local template="$1"
  sed -e "s|@APP_DIR@|$APP_DIR|g" \
    -e "s|@SERVICE_USER@|$service_user|g" \
    -e "s|@ENV_FILE@|$ENV_FILE|g" \
    -e "s|@ROS_DISTRO@|$ros_distro|g" \
    -e "s|@ROS_WS@|$ros_workspace|g" \
    -e "s|@PORT@|$port|g" \
    "$template"
}

write_config() {
  mkdir -p "$CONFIG_DIR"
  if [[ -f "$ENV_FILE" ]]; then
    log "Keeping existing configuration $ENV_FILE"
    return
  fi
  log "Writing configuration $ENV_FILE"
  render_template "$APP_DIR/deploy/config/hemabot.env.in" >"$ENV_FILE"
  chmod 644 "$ENV_FILE"
}

install_services() {
  local service
  mkdir -p "$SYSTEMD_DIR"
  for service in "${SERVICES[@]}"; do
    log "Installing $SYSTEMD_DIR/$service.service"
    render_template "$APP_DIR/deploy/systemd/$service.service.in" >"$SYSTEMD_DIR/$service.service"
    chmod 644 "$SYSTEMD_DIR/$service.service"
  done
  systemctl daemon-reload
  systemctl enable "${SERVICES[@]/%/.service}"
}

open_firewall() {
  if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    log "Allowing TCP port $port in ufw"
    ufw allow "$port/tcp"
  fi
}

start_or_restart_services() {
  if ((start_services == 0)); then
    log "Services enabled; they will start on next boot (--no-start)"
    return
  fi
  log "Starting services"
  systemctl restart "${SERVICES[@]/%/.service}"
}

print_summary() {
  local host_name addresses address url_port=""
  host_name="$(hostname)"
  addresses="$(hostname -I 2>/dev/null || true)"
  [[ "$port" == "80" ]] || url_port=":$port"
  echo
  log "Done. Open the interface from a phone or computer on the same network:"
  echo "    http://$host_name.local$url_port"
  for address in $addresses; do
    [[ "$address" == *:* ]] && continue # skip IPv6
    echo "    http://$address$url_port"
  done
  echo
  echo "Useful commands:"
  echo "    systemctl status hemabot-ros hemabot-ui"
  echo "    journalctl -u hemabot-ui -u hemabot-ros -f"
  echo "    $APP_DIR/.venv/bin/hemabot-ui doctor   (after: source $ROS_ROOT/$ros_distro/setup.bash)"
  echo
  echo "Note: log out and back in for new group memberships to apply to your shell."
}

main() {
  parse_args "$@"
  require_root
  resolve_user
  check_ros
  install_system_packages
  grant_hardware_access
  create_virtualenv
  write_config
  install_services
  open_firewall
  start_or_restart_services
  print_summary
}

main "$@"
