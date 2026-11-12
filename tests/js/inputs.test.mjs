import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { joystickVector, knobOffset, VirtualJoystick } from "../../src/hemabot_ui/web/static/js/inputs/joystick.js";
import { intentFromKeys, KeyboardDrive } from "../../src/hemabot_ui/web/static/js/inputs/keyboard.js";
import { FakeElement, keyEvent, pointerEvent } from "./fakes.mjs";

const close = (actual, expected, epsilon = 1e-9) =>
  assert.ok(Math.abs(actual - expected) < epsilon, `${actual} != ${expected}`);

describe("joystickVector", () => {
  it("is zero at the center and inside the deadzone", () => {
    assert.deepEqual(joystickVector(0, 0, 100), { x: 0, y: 0 });
    assert.deepEqual(joystickVector(5, -5, 100, 0.12), { x: 0, y: 0 });
  });

  it("maps screen up to positive y and right to positive x", () => {
    close(joystickVector(0, -100, 100, 0).y, 1);
    close(joystickVector(100, 0, 100, 0).x, 1);
    close(joystickVector(0, 100, 100, 0).y, -1);
    close(joystickVector(-100, 0, 100, 0).x, -1);
  });

  it("never exceeds unit magnitude, even beyond the radius", () => {
    for (const [dx, dy] of [[500, 0], [300, -300], [-80, 90], [1e6, 1e6]]) {
      const v = joystickVector(dx, dy, 100);
      assert.ok(Math.hypot(v.x, v.y) <= 1 + 1e-12, `${dx},${dy}`);
    }
  });

  it("starts from zero right outside the deadzone (no jump)", () => {
    const v = joystickVector(0, -12.5, 100, 0.12);
    assert.ok(Math.hypot(v.x, v.y) < 0.01);
  });

  it("handles a degenerate radius", () => {
    assert.deepEqual(joystickVector(10, 10, 0), { x: 0, y: 0 });
  });
});

describe("knobOffset", () => {
  it("follows the pointer inside the radius and clamps outside", () => {
    assert.deepEqual(knobOffset(10, -20, 100), { x: 10, y: -20 });
    const clamped = knobOffset(300, 400, 100);
    close(Math.hypot(clamped.x, clamped.y), 100);
  });
});

describe("VirtualJoystick", () => {
  function setup() {
    const base = new FakeElement({ left: 0, top: 0, size: 200 }); // center at (100, 100)
    const knob = new FakeElement();
    const calls = [];
    const joystick = new VirtualJoystick(base, knob, (vector, phase) => calls.push({ ...vector, phase }));
    return { base, knob, joystick, calls };
  }

  it("ignores touches while disabled", () => {
    const { base, joystick, calls } = setup();
    base.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 0 }));
    assert.equal(joystick.active, false);
    assert.deepEqual(calls, []);
  });

  it("reports start, move and end phases", () => {
    const { base, joystick, calls } = setup();
    joystick.enabled = true;
    base.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 0 }));
    assert.equal(joystick.active, true);
    assert.ok(joystick.vector.y > 0.9, "dragging up means forward");
    base.dispatchEvent(pointerEvent("pointermove", { clientX: 200, clientY: 100 }));
    assert.ok(joystick.vector.x > 0.9);
    base.dispatchEvent(pointerEvent("pointerup"));
    assert.deepEqual(calls.map((c) => c.phase), ["start", "move", "end"]);
    assert.deepEqual(joystick.vector, { x: 0, y: 0 });
    assert.equal(joystick.active, false);
  });

  it("ignores a second finger", () => {
    const { base, joystick } = setup();
    joystick.enabled = true;
    base.dispatchEvent(pointerEvent("pointerdown", { pointerId: 1, clientX: 100, clientY: 0 }));
    base.dispatchEvent(pointerEvent("pointermove", { pointerId: 2, clientX: 100, clientY: 200 }));
    base.dispatchEvent(pointerEvent("pointerup", { pointerId: 2 }));
    assert.equal(joystick.active, true);
    assert.ok(joystick.vector.y > 0.9);
  });

  it("stops when the gesture is cancelled by the browser", () => {
    const { base, joystick, calls } = setup();
    joystick.enabled = true;
    base.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 0 }));
    base.dispatchEvent(pointerEvent("pointercancel"));
    assert.equal(joystick.active, false);
    assert.equal(calls.at(-1).phase, "end");
  });

  it("disabling during a gesture releases the joystick", () => {
    const { base, joystick, calls } = setup();
    joystick.enabled = true;
    base.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 0 }));
    joystick.enabled = false;
    assert.equal(joystick.active, false);
    assert.equal(calls.at(-1).phase, "end");
    assert.equal(base.dataset.enabled, "false");
    assert.equal(base.captured.size, 0);
  });
});

describe("intentFromKeys", () => {
  it("maps WASD and arrows", () => {
    assert.deepEqual(intentFromKeys(new Set(["KeyW"])), { linear: 1, angular: 0 });
    assert.deepEqual(intentFromKeys(new Set(["ArrowDown"])), { linear: -1, angular: 0 });
    assert.deepEqual(intentFromKeys(new Set(["KeyA"])), { linear: 0, angular: 1 });
    assert.deepEqual(intentFromKeys(new Set(["ArrowRight"])), { linear: 0, angular: -1 });
    assert.deepEqual(intentFromKeys(new Set(["KeyW", "KeyD"])), { linear: 1, angular: -1 });
  });

  it("cancels opposite keys and counts duplicates once", () => {
    assert.deepEqual(intentFromKeys(new Set(["KeyW", "KeyS"])), { linear: 0, angular: 0 });
    assert.deepEqual(intentFromKeys(new Set(["KeyW", "ArrowUp"])), { linear: 1, angular: 0 });
  });
});

describe("KeyboardDrive", () => {
  function setup() {
    const target = new EventTarget();
    const counters = { change: 0, stop: 0 };
    const keyboard = new KeyboardDrive(target, {
      onChange: () => counters.change++,
      onStop: () => counters.stop++,
    });
    return { target, keyboard, counters };
  }

  it("does not drive while disabled but still prevents scrolling", () => {
    const { target, keyboard, counters } = setup();
    const event = keyEvent("keydown", "ArrowUp");
    target.dispatchEvent(event);
    assert.equal(event.defaultPrevented, true);
    assert.equal(counters.change, 0);
    assert.deepEqual(keyboard.intent, { linear: 0, angular: 0 });
  });

  it("tracks pressed keys when enabled", () => {
    const { target, keyboard, counters } = setup();
    keyboard.enabled = true;
    target.dispatchEvent(keyEvent("keydown", "KeyW"));
    target.dispatchEvent(keyEvent("keydown", "KeyW", { repeat: true }));
    assert.deepEqual(keyboard.intent, { linear: 1, angular: 0 });
    assert.equal(counters.change, 1, "auto-repeat must not re-notify");
    target.dispatchEvent(keyEvent("keyup", "KeyW"));
    assert.deepEqual(keyboard.intent, { linear: 0, angular: 0 });
    assert.equal(counters.change, 2);
  });

  it("clears on window blur (keyup would be lost)", () => {
    const { target, keyboard } = setup();
    keyboard.enabled = true;
    target.dispatchEvent(keyEvent("keydown", "KeyA"));
    target.dispatchEvent(new Event("blur"));
    assert.equal(keyboard.active, false);
  });

  it("space triggers stop once, even when disabled", () => {
    const { target, counters } = setup();
    target.dispatchEvent(keyEvent("keydown", "Space"));
    target.dispatchEvent(keyEvent("keydown", "Space", { repeat: true }));
    assert.equal(counters.stop, 1);
  });

  it("ignores shortcuts and typing in text fields", () => {
    const { target, keyboard } = setup();
    keyboard.enabled = true;
    target.dispatchEvent(keyEvent("keydown", "KeyW", { ctrlKey: true }));
    const textField = { closest: (selector) => (selector.includes("input") ? {} : null) };
    target.dispatchEvent(keyEvent("keydown", "KeyW", { target: textField }));
    assert.equal(keyboard.active, false);
  });

  it("disabling clears pressed keys", () => {
    const { target, keyboard } = setup();
    keyboard.enabled = true;
    target.dispatchEvent(keyEvent("keydown", "KeyW"));
    keyboard.enabled = false;
    assert.equal(keyboard.active, false);
  });
});
