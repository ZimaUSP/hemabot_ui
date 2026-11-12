// Application controller: wires connection, session state, inputs and view together.

import { DriveLoop } from "./drive-loop.js";
import { texts } from "./i18n.js";
import { combineIntent, toVelocity } from "./intent.js";
import { messages, ServerMessageType } from "./protocol.js";
import * as session from "./session.js";

const SPEED_STORAGE_KEY = "hemabot.speedPercent";
const DEFAULT_SPEED_PERCENT = 50;

export class TeleopApp {
  #connection;
  #view;
  #joystick;
  #keyboard;
  #storage;
  #confirm;
  #session = session.initialSession;
  #speedPercent;
  #driveLoop;

  /**
   * @param {object} deps
   * @param {import("./connection.js").TeleopConnection} deps.connection
   * @param {import("./view.js").TeleopView} deps.view
   * @param {import("./inputs/joystick.js").VirtualJoystick} deps.joystick
   * @param {import("./inputs/keyboard.js").KeyboardDrive} deps.keyboard
   * @param {Storage | null} deps.storage
   * @param {(text: string) => boolean} deps.confirm
   * @param {{setInterval: Function, clearInterval: Function}} [deps.timers]
   */
  constructor({ connection, view, joystick, keyboard, storage, confirm, timers = globalThis }) {
    this.#connection = connection;
    this.#view = view;
    this.#joystick = joystick;
    this.#keyboard = keyboard;
    this.#storage = storage;
    this.#confirm = confirm;
    this.#speedPercent = this.#loadSpeed();
    this.#driveLoop = new DriveLoop({
      readIntent: () => this.#currentIntent(),
      sendDrive: (intent) => this.#connection.send(messages.drive(intent.linear, intent.angular)),
      timers,
    });
  }

  start() {
    this.#view.bindActions({
      onAcquire: () => this.#connection.send(messages.acquire(false)),
      onTakeover: () => {
        if (this.#confirm(texts.confirmTakeover)) this.#connection.send(messages.acquire(true));
      },
      onRelease: () => this.#connection.send(messages.release()),
      onStop: () => this.emergencyStop(),
      onSpeedChange: (percent) => this.#setSpeed(percent),
    });
    this.#connection.addEventListener("open", () => this.#apply(session.onConnectionOpened));
    this.#connection.addEventListener("close", () => this.#apply(session.onConnectionClosed));
    this.#connection.addEventListener("message", (event) => this.#onMessage(event.detail));
    this.#render();
    this.#connection.connect();
  }

  /** Called whenever an input device changes (joystick touched/released, key pressed). */
  inputChanged() {
    this.#view.renderVelocity(toVelocity(this.#currentIntent(), this.#session.limits));
  }

  /** Called at the edges of a gesture to send without waiting for the next tick. */
  inputEdge() {
    this.inputChanged();
    if (session.isPilot(this.#session)) this.#driveLoop.tick();
  }

  emergencyStop() {
    this.#releaseInputs();
    if (this.#connection.send(messages.stop())) this.#view.toast(texts.stopped);
  }

  /** The page went to background: never keep driving blind. */
  suspend() {
    this.#releaseInputs();
    if (session.isPilot(this.#session)) this.#driveLoop.tick();
  }

  #onMessage(message) {
    if (message?.type === ServerMessageType.ERROR) {
      this.#view.toast(texts.errors[message.code] ?? texts.unknownError);
      return;
    }
    this.#apply((current) => session.onServerMessage(current, message));
  }

  #apply(transition) {
    const wasPilot = session.isPilot(this.#session);
    this.#session = transition(this.#session);
    const nowPilot = session.isPilot(this.#session);
    if (wasPilot && !nowPilot) {
      this.#releaseInputs();
      this.#driveLoop.stop();
      if (this.#session.connected && this.#session.pilotId !== null) {
        this.#view.toast(texts.lostControl);
      }
    } else if (!wasPilot && nowPilot) {
      this.#driveLoop.reset();
      this.#driveLoop.start();
    }
    this.#joystick.enabled = nowPilot;
    this.#keyboard.enabled = nowPilot;
    this.#render();
  }

  #render() {
    this.#view.render(session.view(this.#session));
    this.#view.renderSpeed(this.#speedPercent, this.#session.limits);
    this.inputChanged();
  }

  #releaseInputs() {
    this.#joystick.release();
    this.#keyboard.clear();
    this.inputChanged();
  }

  #currentIntent() {
    if (!session.isPilot(this.#session)) return { linear: 0, angular: 0 };
    return combineIntent({
      joystickActive: this.#joystick.active,
      joystickVector: this.#joystick.vector,
      keyboardIntent: this.#keyboard.intent,
      speed: this.#speedPercent / 100,
    });
  }

  #setSpeed(percent) {
    this.#speedPercent = percent;
    try {
      this.#storage?.setItem(SPEED_STORAGE_KEY, String(percent));
    } catch {
      // Storage may be unavailable (private mode); the setting just won't persist.
    }
    this.#view.renderSpeed(percent, this.#session.limits);
    this.inputChanged();
  }

  #loadSpeed() {
    let stored = null;
    try {
      stored = Number(this.#storage?.getItem(SPEED_STORAGE_KEY));
    } catch {
      stored = null;
    }
    return Number.isFinite(stored) && stored >= 10 && stored <= 100
      ? stored
      : DEFAULT_SPEED_PERCENT;
  }
}
