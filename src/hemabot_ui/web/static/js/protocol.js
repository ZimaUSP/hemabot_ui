// Client side of the teleoperation WebSocket protocol (see hemabot_ui/web/protocol.py).

export const ServerMessageType = Object.freeze({
  WELCOME: "welcome",
  STATE: "state",
  ERROR: "error",
});

export const LinkState = Object.freeze({
  CONNECTED: "connected",
  WAITING: "waiting",
  OFFLINE: "offline",
});

export const ErrorCode = Object.freeze({
  INVALID_MESSAGE: "invalid_message",
  NOT_PILOT: "not_pilot",
  PILOT_BUSY: "pilot_busy",
});

const clampUnit = (value) => Math.max(-1, Math.min(1, value));

/** Round to 3 decimals to keep frames small; avoids "-0" which JSON keeps as 0 anyway. */
const compact = (value) => Math.round(clampUnit(value) * 1000) / 1000 || 0;

export const messages = Object.freeze({
  acquire: (force = false) => ({ type: "acquire", force }),
  release: () => ({ type: "release" }),
  /** Normalized intent; positive angular turns left (ROS REP 103). */
  drive: (linear, angular) => ({ type: "drive", linear: compact(linear), angular: compact(angular) }),
  stop: () => ({ type: "stop" }),
});

/** Build the WebSocket URL for the page that served this script. */
export function teleopSocketUrl(location) {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws/teleop`;
}
