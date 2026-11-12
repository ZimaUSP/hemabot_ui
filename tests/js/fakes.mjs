// Test doubles shared by the frontend tests (no DOM library needed).

export class FakeTimers {
  #next = 1;
  intervals = new Map();
  timeouts = new Map();

  setInterval(callback, ms) {
    const id = this.#next++;
    this.intervals.set(id, { callback, ms });
    return id;
  }

  clearInterval(id) {
    this.intervals.delete(id);
  }

  setTimeout(callback, ms) {
    const id = this.#next++;
    this.timeouts.set(id, { callback, ms });
    return id;
  }

  clearTimeout(id) {
    this.timeouts.delete(id);
  }

  /** Fire every registered interval once. */
  tickIntervals() {
    for (const { callback } of [...this.intervals.values()]) callback();
  }

  /** Run (and remove) all pending timeouts, returning their delays. */
  flushTimeouts() {
    const delays = [];
    for (const [id, { callback, ms }] of [...this.timeouts]) {
      this.timeouts.delete(id);
      delays.push(ms);
      callback();
    }
    return delays;
  }
}

export class FakeWebSocket extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    super();
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }

  static reset() {
    FakeWebSocket.instances = [];
  }

  static get last() {
    return FakeWebSocket.instances.at(-1);
  }

  send(data) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    this.serverClose();
  }

  // --- test helpers ---
  serverOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  serverSend(message) {
    const data = typeof message === "string" ? message : JSON.stringify(message);
    this.dispatchEvent(Object.assign(new Event("message"), { data }));
  }

  serverClose() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }
}

/** Minimal element supporting what VirtualJoystick needs. */
export class FakeElement extends EventTarget {
  constructor({ left = 0, top = 0, size = 200 } = {}) {
    super();
    this.dataset = {};
    this.style = {};
    this.rect = { left, top, width: size, height: size };
    this.captured = new Set();
  }

  getBoundingClientRect() {
    return this.rect;
  }

  setPointerCapture(id) {
    this.captured.add(id);
  }

  hasPointerCapture(id) {
    return this.captured.has(id);
  }

  releasePointerCapture(id) {
    this.captured.delete(id);
  }
}

export function pointerEvent(type, { pointerId = 1, clientX = 0, clientY = 0 } = {}) {
  const event = new Event(type, { cancelable: true });
  return Object.assign(event, { pointerId, clientX, clientY });
}

export function keyEvent(type, code, extra = {}) {
  const event = new Event(type, { cancelable: true });
  const fields = { code, repeat: false, ctrlKey: false, metaKey: false, altKey: false, ...extra };
  // defineProperty (not assignment) so read-only Event fields such as `target` can be faked.
  for (const [name, value] of Object.entries(fields)) {
    Object.defineProperty(event, name, { value });
  }
  return event;
}
