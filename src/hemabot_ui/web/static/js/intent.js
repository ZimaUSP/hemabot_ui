// Combines the input devices into one normalized drive intent.

/**
 * @param {object} inputs
 * @param {boolean} inputs.joystickActive  the on-screen joystick is being touched
 * @param {{x: number, y: number}} inputs.joystickVector  x right, y up, in [-1, 1]
 * @param {{linear: number, angular: number}} inputs.keyboardIntent
 * @param {number} speed  speed factor in [0, 1] chosen by the operator
 * @returns {{linear: number, angular: number}} positive angular turns left
 */
export function combineIntent({ joystickActive, joystickVector, keyboardIntent, speed }) {
  // The joystick wins while touched: it is the more deliberate, analog input.
  const base = joystickActive
    ? { linear: joystickVector.y, angular: -joystickVector.x }
    : keyboardIntent;
  const factor = Math.max(0, Math.min(1, speed));
  return { linear: base.linear * factor || 0, angular: base.angular * factor || 0 };
}

/** Physical velocity shown to the operator for a normalized intent. */
export function toVelocity(intent, limits) {
  if (!limits) return { linear: 0, angular: 0 };
  return {
    linear: intent.linear * limits.max_linear,
    angular: intent.angular * limits.max_angular,
  };
}
