# shellcheck shell=bash
# Helpers to load ROS 2 and the Hemabot workspace into the current shell.
# Sourced by the service start scripts; configuration comes from /etc/hemabot/hemabot.env:
#   HEMABOT_ROS_SETUP  ROS 2 distro setup file (default /opt/ros/humble/setup.bash)
#   HEMABOT_ROS_WS     path of the hemabot_ros2 colcon workspace

hemabot_log() {
  echo "[$(basename "$0")] $*" >&2
}

# ROS setup files reference unset variables and run commands that may fail harmlessly,
# so they are sourced with `set -e` and `set -u` temporarily disabled.
_hemabot_source_unchecked() {
  local saved_options=$-
  local status=0
  set +eu
  # shellcheck disable=SC1090
  source "$1" || status=$?
  [[ $saved_options == *e* ]] && set -e
  [[ $saved_options == *u* ]] && set -u
  return "$status"
}

hemabot_source_ros_distro() {
  local setup_file="${HEMABOT_ROS_SETUP:-/opt/ros/humble/setup.bash}"
  if [[ ! -f "$setup_file" ]]; then
    hemabot_log "ROS 2 setup file not found: $setup_file (is ROS 2 installed?)"
    return 1
  fi
  _hemabot_source_unchecked "$setup_file"
}

# Usage: hemabot_source_workspace required|optional
hemabot_source_workspace() {
  local requirement="$1"
  local workspace="${HEMABOT_ROS_WS:-}"
  local setup_file="$workspace/install/setup.bash"
  if [[ -z "$workspace" || ! -f "$setup_file" ]]; then
    hemabot_log "workspace setup not found: '$setup_file'. Set HEMABOT_ROS_WS and build it with colcon."
    [[ "$requirement" == "optional" ]] && return 0
    return 1
  fi
  _hemabot_source_unchecked "$setup_file"
}
