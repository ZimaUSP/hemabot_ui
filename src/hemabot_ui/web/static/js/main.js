// Entry point: builds the real browser dependencies and starts the app.

import { TeleopApp } from "./app.js";
import { TeleopConnection } from "./connection.js";
import { KeyboardDrive } from "./inputs/keyboard.js";
import { VirtualJoystick } from "./inputs/joystick.js";
import { teleopSocketUrl } from "./protocol.js";
import { TeleopView } from "./view.js";

function safeLocalStorage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const view = new TeleopView(document);
let app = null;

const { base, knob } = view.joystickElements;
const joystick = new VirtualJoystick(base, knob, (_vector, phase) => {
  // Start/end of a gesture is sent immediately; motion in between rides the drive loop.
  if (phase === "move") app?.inputChanged();
  else app?.inputEdge();
});

const keyboard = new KeyboardDrive(window, {
  onChange: () => app?.inputEdge(),
  onStop: () => app?.emergencyStop(),
});

app = new TeleopApp({
  connection: new TeleopConnection(teleopSocketUrl(window.location)),
  view,
  joystick,
  keyboard,
  storage: safeLocalStorage(),
  confirm: (text) => window.confirm(text),
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") app.suspend();
});
window.addEventListener("pagehide", () => app.suspend());

app.start();
