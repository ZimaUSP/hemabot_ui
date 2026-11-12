// Keyboard driving for desktop browsers. Uses `KeyboardEvent.code`, so it works with
// any layout (QWERTY, ABNT2, ...).

const FORWARD = new Set(["KeyW", "ArrowUp"]);
const BACKWARD = new Set(["KeyS", "ArrowDown"]);
const LEFT = new Set(["KeyA", "ArrowLeft"]);
const RIGHT = new Set(["KeyD", "ArrowRight"]);
const STOP = new Set(["Space"]);

export const DRIVE_KEYS = new Set([...FORWARD, ...BACKWARD, ...LEFT, ...RIGHT]);

const anyPressed = (pressed, keys) => [...keys].some((key) => pressed.has(key));

/** Normalized intent for a set of pressed key codes; positive angular turns left. */
export function intentFromKeys(pressed) {
  const linear = Number(anyPressed(pressed, FORWARD)) - Number(anyPressed(pressed, BACKWARD));
  const angular = Number(anyPressed(pressed, LEFT)) - Number(anyPressed(pressed, RIGHT));
  return { linear, angular };
}

/** Typing in form fields must not drive the robot. */
function isEditable(target) {
  if (!target || typeof target.closest !== "function") return false;
  return target.closest("input:not([type=range]), textarea, select, [contenteditable]") !== null;
}

export class KeyboardDrive {
  #pressed = new Set();
  #onChange;
  #onStop;
  #enabled = false;

  /**
   * @param {EventTarget} target  usually `window`
   * @param {{onChange: () => void, onStop: () => void}} callbacks
   */
  constructor(target, { onChange, onStop }) {
    this.#onChange = onChange;
    this.#onStop = onStop;
    target.addEventListener("keydown", (event) => this.#onKeyDown(event));
    target.addEventListener("keyup", (event) => this.#onKeyUp(event));
    // Keys released while the window is unfocused never fire "keyup".
    target.addEventListener("blur", () => this.clear());
  }

  get intent() {
    return intentFromKeys(this.#pressed);
  }

  get active() {
    return this.#pressed.size > 0;
  }

  set enabled(value) {
    this.#enabled = Boolean(value);
    if (!this.#enabled) this.clear();
  }

  clear() {
    if (this.#pressed.size === 0) return;
    this.#pressed.clear();
    this.#onChange();
  }

  #onKeyDown(event) {
    if (isEditable(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (STOP.has(event.code)) {
      event.preventDefault();
      if (!event.repeat) this.#onStop();
      return;
    }
    if (!DRIVE_KEYS.has(event.code)) return;
    event.preventDefault(); // no page scrolling / slider changes with arrows
    if (!this.#enabled || this.#pressed.has(event.code)) return;
    this.#pressed.add(event.code);
    this.#onChange();
  }

  #onKeyUp(event) {
    if (!this.#pressed.delete(event.code)) return;
    this.#onChange();
  }
}
