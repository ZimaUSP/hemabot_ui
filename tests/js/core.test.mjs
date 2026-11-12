import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { TeleopConnection } from "../../src/hemabot_ui/web/static/js/connection.js";
import { DriveLoop } from "../../src/hemabot_ui/web/static/js/drive-loop.js";
import { combineIntent, toVelocity } from "../../src/hemabot_ui/web/static/js/intent.js";
import { messages, teleopSocketUrl } from "../../src/hemabot_ui/web/static/js/protocol.js";
import * as session from "../../src/hemabot_ui/web/static/js/session.js";
import { FakeTimers, FakeWebSocket } from "./fakes.mjs";

describe("protocol", () => {
  it("builds drive messages clamped to [-1, 1] and compact", () => {
    assert.deepEqual(messages.drive(2, -3), { type: "drive", linear: 1, angular: -1 });
    assert.deepEqual(messages.drive(0.123456, -0), { type: "drive", linear: 0.123, angular: 0 });
    assert.ok(!Object.is(messages.drive(-0.0001, 0).linear, -0), "no negative zero");
  });

  it("builds control messages", () => {
    assert.deepEqual(messages.acquire(), { type: "acquire", force: false });
    assert.deepEqual(messages.acquire(true), { type: "acquire", force: true });
    assert.deepEqual(messages.release(), { type: "release" });
    assert.deepEqual(messages.stop(), { type: "stop" });
  });

  it("derives the socket URL from the page location", () => {
    assert.equal(teleopSocketUrl({ protocol: "http:", host: "hemabot.local" }), "ws://hemabot.local/ws/teleop");
    assert.equal(teleopSocketUrl({ protocol: "https:", host: "x:8443" }), "wss://x:8443/ws/teleop");
  });
});

describe("combineIntent", () => {
  const keyboardIntent = { linear: 1, angular: 0 };

  it("maps joystick up to forward and right to a right turn (negative angular)", () => {
    const intent = combineIntent({
      joystickActive: true, joystickVector: { x: 1, y: 0.5 }, keyboardIntent, speed: 1,
    });
    assert.deepEqual(intent, { linear: 0.5, angular: -1 });
  });

  it("prefers the joystick while touched, otherwise uses the keyboard", () => {
    const idleStick = { x: 0, y: 0 };
    assert.deepEqual(
      combineIntent({ joystickActive: true, joystickVector: idleStick, keyboardIntent, speed: 1 }),
      { linear: 0, angular: 0 },
    );
    assert.deepEqual(
      combineIntent({ joystickActive: false, joystickVector: idleStick, keyboardIntent, speed: 1 }),
      { linear: 1, angular: 0 },
    );
  });

  it("scales by the speed factor, clamped to [0, 1]", () => {
    const args = { joystickActive: false, joystickVector: { x: 0, y: 0 }, keyboardIntent };
    assert.deepEqual(combineIntent({ ...args, speed: 0.3 }), { linear: 0.3, angular: 0 });
    assert.deepEqual(combineIntent({ ...args, speed: 7 }), { linear: 1, angular: 0 });
    assert.deepEqual(combineIntent({ ...args, speed: -1 }), { linear: 0, angular: 0 });
  });

  it("converts to physical velocity", () => {
    const limits = { max_linear: 0.4, max_angular: 1.0 };
    assert.deepEqual(toVelocity({ linear: 0.5, angular: -1 }, limits), { linear: 0.2, angular: -1 });
    assert.deepEqual(toVelocity({ linear: 1, angular: 1 }, null), { linear: 0, angular: 0 });
  });
});

describe("DriveLoop", () => {
  let timers;
  let sent;
  let intent;
  let loop;

  beforeEach(() => {
    timers = new FakeTimers();
    sent = [];
    intent = { linear: 0, angular: 0 };
    loop = new DriveLoop({ sendDrive: (i) => sent.push(i), readIntent: () => intent, timers });
    loop.start();
  });

  it("sends nothing while idle", () => {
    timers.tickIntervals();
    timers.tickIntervals();
    assert.deepEqual(sent, []);
  });

  it("streams the intent while moving", () => {
    intent = { linear: 0.5, angular: 0 };
    timers.tickIntervals();
    timers.tickIntervals();
    timers.tickIntervals();
    assert.equal(sent.length, 3);
    assert.ok(loop.isMoving);
  });

  it("sends exactly one idle message when the operator lets go", () => {
    intent = { linear: 0.5, angular: 0 };
    timers.tickIntervals();
    intent = { linear: 0, angular: 0 };
    timers.tickIntervals();
    timers.tickIntervals();
    assert.deepEqual(sent, [{ linear: 0.5, angular: 0 }, { linear: 0, angular: 0 }]);
  });

  it("runs at 10 Hz by default and stops cleanly", () => {
    assert.deepEqual([...timers.intervals.values()].map((t) => t.ms), [100]);
    loop.start();
    assert.equal(timers.intervals.size, 1, "start is idempotent");
    loop.stop();
    assert.equal(timers.intervals.size, 0);
  });

  it("reset forgets motion so no stale idle message is sent", () => {
    intent = { linear: 0.5, angular: 0 };
    timers.tickIntervals();
    loop.reset();
    intent = { linear: 0, angular: 0 };
    timers.tickIntervals();
    assert.equal(sent.length, 1);
  });
});

describe("session", () => {
  const welcome = { type: "welcome", client_id: "me", limits: { max_linear: 0.4, max_angular: 1 } };
  const state = (pilot) => ({
    type: "state", pilot_id: pilot, clients: 2, robot: { link: "connected", detail: "ok" },
  });
  const connected = () =>
    session.onServerMessage(session.onConnectionOpened(session.initialSession), welcome);

  it("starts disconnected", () => {
    const view = session.view(session.initialSession);
    assert.equal(view.connected, false);
    assert.equal(view.canAcquire, false);
    assert.equal(view.canStop, false);
  });

  it("can acquire when nobody is the pilot", () => {
    const view = session.view(session.onServerMessage(connected(), state(null)));
    assert.equal(view.canAcquire, true);
    assert.equal(view.isPilot, false);
    assert.equal(view.otherPilot, false);
  });

  it("recognizes itself as the pilot", () => {
    const s = session.onServerMessage(connected(), state("me"));
    assert.equal(session.isPilot(s), true);
    assert.equal(session.view(s).canAcquire, false);
  });

  it("recognizes another pilot", () => {
    const view = session.view(session.onServerMessage(connected(), state("other")));
    assert.equal(view.otherPilot, true);
    assert.equal(view.canAcquire, false);
  });

  it("forgets identity and pilot role on disconnect but keeps limits", () => {
    const s = session.onConnectionClosed(session.onServerMessage(connected(), state("me")));
    assert.equal(session.isPilot(s), false);
    assert.equal(s.clientId, null);
    assert.deepEqual(s.limits, welcome.limits);
  });

  it("ignores unknown messages", () => {
    const s = connected();
    assert.equal(session.onServerMessage(s, { type: "future" }), s);
  });
});

describe("TeleopConnection", () => {
  let timers;
  let connection;
  let received;

  beforeEach(() => {
    FakeWebSocket.reset();
    timers = new FakeTimers();
    connection = new TeleopConnection("ws://robot/ws/teleop", {
      WebSocketImpl: FakeWebSocket, reconnectDelaysMs: [100, 200, 400], timers,
    });
    received = [];
    connection.addEventListener("message", (event) => received.push(event.detail));
    connection.connect();
  });

  it("sends JSON only while open", () => {
    assert.equal(connection.send({ type: "stop" }), false);
    FakeWebSocket.last.serverOpen();
    assert.equal(connection.send({ type: "stop" }), true);
    assert.deepEqual(FakeWebSocket.last.sent, [{ type: "stop" }]);
  });

  it("parses messages and ignores malformed frames", () => {
    FakeWebSocket.last.serverOpen();
    FakeWebSocket.last.serverSend({ type: "state" });
    FakeWebSocket.last.serverSend("{not json");
    assert.deepEqual(received, [{ type: "state" }]);
  });

  it("reconnects with backoff and resets it after success", () => {
    FakeWebSocket.last.serverClose();
    assert.deepEqual(timers.flushTimeouts(), [100]);
    FakeWebSocket.last.serverClose();
    assert.deepEqual(timers.flushTimeouts(), [200]);
    FakeWebSocket.last.serverClose();
    assert.deepEqual(timers.flushTimeouts(), [400]);
    FakeWebSocket.last.serverClose();
    assert.deepEqual(timers.flushTimeouts(), [400], "delay is capped");
    FakeWebSocket.last.serverOpen();
    FakeWebSocket.last.serverClose();
    assert.deepEqual(timers.flushTimeouts(), [100]);
    assert.equal(FakeWebSocket.instances.length, 6);
  });

  it("does not reconnect after an explicit close", () => {
    FakeWebSocket.last.serverOpen();
    connection.close();
    assert.equal(timers.timeouts.size, 0);
  });

  it("emits open and close events", () => {
    const events = [];
    connection.addEventListener("open", () => events.push("open"));
    connection.addEventListener("close", () => events.push("close"));
    FakeWebSocket.last.serverOpen();
    FakeWebSocket.last.serverClose();
    assert.deepEqual(events, ["open", "close"]);
  });
});
