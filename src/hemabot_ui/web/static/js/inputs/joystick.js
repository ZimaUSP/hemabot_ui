// On-screen joystick driven by pointer events (touch, mouse and pen alike).

export const DEFAULT_DEADZONE = 0.12;

/**
 * Convert a pointer offset from the joystick center into a normalized vector.
 *
 * @param {number} dx  horizontal offset in pixels (right is positive)
 * @param {number} dy  vertical offset in pixels (down is positive, as on screen)
 * @param {number} radius  pixels corresponding to full deflection
 * @param {number} deadzone  fraction of the radius that maps to zero
 * @returns {{x: number, y: number}} x right-positive, y up-positive, magnitude <= 1
 */
export function joystickVector(dx, dy, radius, deadzone = DEFAULT_DEADZONE) {
  if (!(radius > 0)) return { x: 0, y: 0 };
  const distance = Math.hypot(dx, dy);
  const magnitude = Math.min(distance / radius, 1);
  if (magnitude <= deadzone || distance === 0) return { x: 0, y: 0 };
  // Rescale so the output starts at 0 right outside the deadzone (no jump).
  const scaled = (magnitude - deadzone) / (1 - deadzone);
  return { x: (dx / distance) * scaled || 0, y: (-dy / distance) * scaled || 0 };
}

/** Knob offset in pixels for a pointer offset, clamped to the joystick radius. */
export function knobOffset(dx, dy, radius) {
  const distance = Math.hypot(dx, dy);
  if (distance <= radius || distance === 0) return { x: dx, y: dy };
  return { x: (dx / distance) * radius, y: (dy / distance) * radius };
}

export class VirtualJoystick {
  #base;
  #knob;
  #onChange;
  #pointerId = null;
  #enabled = false;
  #vector = { x: 0, y: 0 };

  /**
   * @param {HTMLElement} base  the circular area receiving pointer events
   * @param {HTMLElement} knob  the element moved under the finger
   * @param {(vector: {x: number, y: number}, phase: "start" | "move" | "end") => void} onChange
   *   called with "start" when touched, "move" while dragging and "end" when released
   */
  constructor(base, knob, onChange) {
    this.#base = base;
    this.#knob = knob;
    this.#onChange = onChange;
    base.addEventListener("pointerdown", (event) => this.#onDown(event));
    base.addEventListener("pointermove", (event) => this.#onMove(event));
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      base.addEventListener(type, (event) => this.#onUp(event));
    }
    base.dataset.active = "false";
  }

  get vector() {
    return this.#vector;
  }

  get active() {
    return this.#pointerId !== null;
  }

  set enabled(value) {
    this.#enabled = Boolean(value);
    this.#base.dataset.enabled = String(this.#enabled);
    if (!this.#enabled) this.release();
  }

  /** Return the knob to the center and report an idle vector. */
  release() {
    const wasActive = this.active;
    if (this.#pointerId !== null && this.#base.hasPointerCapture?.(this.#pointerId)) {
      this.#base.releasePointerCapture(this.#pointerId);
    }
    this.#pointerId = null;
    this.#base.dataset.active = "false";
    this.#update(0, 0, 1);
    if (wasActive) this.#onChange(this.#vector, "end");
  }

  #onDown(event) {
    if (!this.#enabled || this.#pointerId !== null) return;
    event.preventDefault();
    this.#pointerId = event.pointerId;
    this.#base.setPointerCapture?.(event.pointerId);
    this.#base.dataset.active = "true";
    this.#track(event, "start");
  }

  #onMove(event) {
    if (event.pointerId !== this.#pointerId) return;
    event.preventDefault();
    this.#track(event, "move");
  }

  #onUp(event) {
    if (event.pointerId !== this.#pointerId) return;
    this.release();
  }

  #track(event, phase) {
    const rect = this.#base.getBoundingClientRect();
    const radius = rect.width / 2;
    const dx = event.clientX - (rect.left + radius);
    const dy = event.clientY - (rect.top + rect.height / 2);
    this.#update(dx, dy, radius);
    this.#onChange(this.#vector, phase);
  }

  #update(dx, dy, radius) {
    // The knob travels until its edge touches the rim.
    const travel = radius * 0.66;
    this.#vector = joystickVector(dx, dy, travel);
    const offset = knobOffset(dx, dy, travel);
    this.#knob.style.transform =
      `translate(calc(-50% + ${offset.x}px), calc(-50% + ${offset.y}px))`;
  }
}
