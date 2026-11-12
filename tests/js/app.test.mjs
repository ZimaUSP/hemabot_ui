import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { TeleopApp } from "../../src/hemabot_ui/web/static/js/app.js";
import { TeleopConnection } from "../../src/hemabot_ui/web/static/js/connection.js";
import { texts } from "../../src/hemabot_ui/web/static/js/i18n.js";
import { FakeTimers, FakeWebSocket } from "./fakes.mjs";

class FakeView {
  renders = [];
  speeds = [];
  velocities = [];
  toasts = [];
  actions = null;

  bindActions(actions) { this.actions = actions; }
  render(state) { this.renders.push(state); }
  renderSpeed(percent, limits) { this.speeds.push({ percent, limits }); }
  renderVelocity(velocity) { this.velocities.push(velocity); }
  toast(text) { this.toasts.push(text); }
  get last() { return this.renders.at(-1); }
}

class FakeInput {
  enabled = false;
  active = false;
  vector = { x: 0, y: 0 };
  intent = { linear: 0, angular: 0 };
  releases = 0;
  release() { this.releases++; this.active = false; this.vector = { x: 0, y: 0 }; }
  clear() { this.releases++; this.intent = { linear: 0, angular: 0 }; }
}

class MemoryStorage {
  data = new Map();
  getItem(key) { return this.data.has(key) ? this.data.get(key) : null; }
  setItem(key, value) { this.data.set(key, String(value)); }
}

const WELCOME = { type: "welcome", client_id: "me", limits: { max_linear: 0.4, max_angular: 1.0 } };
const state = (pilot) => ({
  type: "state", pilot_id: pilot, clients: 1, robot: { link: "connected", detail: "" },
});

describe("TeleopApp", () => {
  let timers;
  let view;
  let joystick;
  let keyboard;
  let storage;
  let confirmAnswer;
  let app;
  const socket = () => FakeWebSocket.last;
  const sent = () => socket().sent;

  function build() {
    const connection = new TeleopConnection("ws://robot/ws/teleop", {
      WebSocketImpl: FakeWebSocket, timers,
    });
    app = new TeleopApp({
      connection, view, joystick, keyboard, storage, timers,
      confirm: () => confirmAnswer,
    });
    app.start();
  }

  function becomePilot() {
    socket().serverOpen();
    socket().serverSend(WELCOME);
    socket().serverSend(state("me"));
  }

  beforeEach(() => {
    FakeWebSocket.reset();
    timers = new FakeTimers();
    view = new FakeView();
    joystick = new FakeInput();
    keyboard = new FakeInput();
    storage = new MemoryStorage();
    confirmAnswer = true;
    build();
  });

  it("connects on start and renders a disconnected state first", () => {
    assert.equal(FakeWebSocket.instances.length, 1);
    assert.equal(view.renders[0].connected, false);
  });

  it("enables inputs and the drive loop only for the pilot", () => {
    socket().serverOpen();
    socket().serverSend(WELCOME);
    socket().serverSend(state(null));
    assert.equal(joystick.enabled, false);
    assert.equal(timers.intervals.size, 0);

    socket().serverSend(state("me"));
    assert.equal(joystick.enabled, true);
    assert.equal(keyboard.enabled, true);
    assert.equal(timers.intervals.size, 1);
    assert.equal(view.last.isPilot, true);
  });

  it("streams joystick input scaled by the speed slider", () => {
    becomePilot();
    view.actions.onSpeedChange(50);
    joystick.active = true;
    joystick.vector = { x: 0, y: 1 };
    app.inputChanged(); // what the real joystick's "move" callback does
    timers.tickIntervals();
    assert.deepEqual(sent().at(-1), { type: "drive", linear: 0.5, angular: 0 });
    assert.deepEqual(view.velocities.at(-1), { linear: 0.2, angular: 0 });
  });

  it("sends an idle drive immediately at the end of a gesture", () => {
    becomePilot();
    joystick.active = true;
    joystick.vector = { x: 0, y: 1 };
    app.inputEdge();
    joystick.active = false;
    joystick.vector = { x: 0, y: 0 };
    app.inputEdge();
    assert.deepEqual(sent().map((m) => m.type), ["drive", "drive"]);
    assert.deepEqual(sent().at(-1), { type: "drive", linear: 0, angular: 0 });
  });

  it("observers never send drive messages", () => {
    socket().serverOpen();
    socket().serverSend(WELCOME);
    socket().serverSend(state("someone-else"));
    joystick.active = true;
    joystick.vector = { x: 0, y: 1 };
    app.inputEdge();
    timers.tickIntervals();
    assert.deepEqual(sent(), []);
  });

  it("losing control releases inputs, stops streaming and warns the user", () => {
    becomePilot();
    joystick.active = true;
    joystick.vector = { x: 0, y: 1 };
    socket().serverSend(state("intruder"));
    assert.equal(joystick.active, false);
    assert.equal(joystick.enabled, false);
    assert.equal(timers.intervals.size, 0);
    assert.deepEqual(view.toasts, [texts.lostControl]);
  });

  it("a dropped connection disables driving without a lost-control toast", () => {
    becomePilot();
    socket().serverClose();
    assert.equal(joystick.enabled, false);
    assert.equal(timers.intervals.size, 0);
    assert.deepEqual(view.toasts, []);
    assert.equal(view.last.connected, false);
  });

  it("emergency stop releases inputs and sends stop", () => {
    becomePilot();
    joystick.active = true;
    view.actions.onStop();
    assert.equal(joystick.active, false);
    assert.deepEqual(sent().at(-1), { type: "stop" });
    assert.deepEqual(view.toasts, [texts.stopped]);
  });

  it("acquire, takeover (with confirmation) and release send the right messages", () => {
    socket().serverOpen();
    view.actions.onAcquire();
    view.actions.onTakeover();
    confirmAnswer = false;
    view.actions.onTakeover();
    view.actions.onRelease();
    assert.deepEqual(sent(), [
      { type: "acquire", force: false },
      { type: "acquire", force: true },
      { type: "release" },
    ]);
  });

  it("shows server errors as translated toasts", () => {
    socket().serverOpen();
    socket().serverSend({ type: "error", code: "pilot_busy", message: "x" });
    socket().serverSend({ type: "error", code: "brand_new_code", message: "x" });
    assert.deepEqual(view.toasts, [texts.errors.pilot_busy, texts.unknownError]);
  });

  it("suspending the page stops motion", () => {
    becomePilot();
    keyboard.intent = { linear: 1, angular: 0 };
    timers.tickIntervals();
    app.suspend();
    assert.deepEqual(sent().at(-1), { type: "drive", linear: 0, angular: 0 });
  });

  it("persists the speed and restores it on the next visit", () => {
    view.actions.onSpeedChange(80);
    assert.equal(storage.getItem("hemabot.speedPercent"), "80");
    view = new FakeView();
    build();
    assert.equal(view.speeds.at(-1).percent, 80);
  });

  it("falls back to the default speed when storage is broken or invalid", () => {
    storage = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
    view = new FakeView();
    build();
    assert.equal(view.speeds.at(-1).percent, 50);
    view.actions.onSpeedChange(30); // must not throw
    storage = new MemoryStorage();
    storage.setItem("hemabot.speedPercent", "9999");
    view = new FakeView();
    build();
    assert.equal(view.speeds.at(-1).percent, 50);
  });
});
