// DOM rendering. Knows the markup in index.html and nothing about the protocol.

import { texts } from "./i18n.js";
import { LinkState } from "./protocol.js";

const TOAST_DURATION_MS = 3500;

const LINK_TONE = {
  [LinkState.CONNECTED]: "ok",
  [LinkState.WAITING]: "warn",
  [LinkState.OFFLINE]: "bad",
};

export class TeleopView {
  #elements;
  #toastTimer = null;

  constructor(doc) {
    const byId = (id) => {
      const element = doc.getElementById(id);
      if (!element) throw new Error(`missing #${id} in index.html`);
      return element;
    };
    this.#elements = {
      serverStatus: byId("server-status"),
      robotStatus: byId("robot-status"),
      pilotMessage: byId("pilot-message"),
      acquire: byId("acquire-button"),
      takeover: byId("takeover-button"),
      release: byId("release-button"),
      stop: byId("stop-button"),
      speed: byId("speed"),
      speedValue: byId("speed-value"),
      speedLimits: byId("speed-limits"),
      linear: byId("telemetry-linear"),
      angular: byId("telemetry-angular"),
      joystick: byId("joystick"),
      joystickKnob: byId("joystick-knob"),
      toast: byId("toast"),
    };
  }

  get joystickElements() {
    return { base: this.#elements.joystick, knob: this.#elements.joystickKnob };
  }

  bindActions({ onAcquire, onTakeover, onRelease, onStop, onSpeedChange }) {
    const e = this.#elements;
    e.acquire.addEventListener("click", onAcquire);
    e.takeover.addEventListener("click", onTakeover);
    e.release.addEventListener("click", onRelease);
    // pointerdown reacts faster than click on touch screens; click covers keyboard use.
    e.stop.addEventListener("pointerdown", onStop);
    e.stop.addEventListener("click", (event) => { if (event.detail === 0) onStop(); });
    e.speed.addEventListener("input", () => onSpeedChange(Number(e.speed.value)));
    // Return focus to the page so arrow keys drive instead of moving the slider.
    e.speed.addEventListener("change", () => e.speed.blur());
  }

  render(state) {
    const e = this.#elements;
    setPill(
      e.serverStatus,
      state.connected ? texts.serverOnline : texts.serverOffline,
      state.connected ? "ok" : "bad",
    );
    const link = state.connected ? state.robotLink : LinkState.OFFLINE;
    setPill(e.robotStatus, texts.robotLink[link] ?? link, LINK_TONE[link] ?? "neutral");

    let message;
    if (!state.connected) message = texts.pilot.disconnected;
    else if (state.isPilot) message = texts.pilot.you;
    else if (state.otherPilot) message = texts.pilot.other;
    else message = texts.pilot.free;
    if (state.connected && state.robotLink !== LinkState.CONNECTED) {
      message += texts.robotWaitingHint;
    }
    e.pilotMessage.textContent = message;

    e.acquire.hidden = state.isPilot || state.otherPilot;
    e.acquire.disabled = !state.canAcquire;
    e.takeover.hidden = !state.otherPilot;
    e.release.hidden = !state.isPilot;
    e.stop.disabled = !state.canStop;
  }

  renderSpeed(percent, limits) {
    const e = this.#elements;
    e.speed.value = String(percent);
    e.speedValue.textContent = `${percent}%`;
    if (limits) {
      const factor = percent / 100;
      e.speedLimits.textContent =
        `máx. ${formatNumber(limits.max_linear * factor)} m/s · ` +
        `${formatNumber(limits.max_angular * factor)} rad/s`;
    }
  }

  renderVelocity(velocity) {
    this.#elements.linear.textContent = `${formatNumber(velocity.linear)} m/s`;
    this.#elements.angular.textContent = `${formatNumber(velocity.angular)} rad/s`;
  }

  toast(text) {
    const toast = this.#elements.toast;
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(this.#toastTimer);
    this.#toastTimer = setTimeout(() => { toast.hidden = true; }, TOAST_DURATION_MS);
  }
}

function setPill(element, text, tone) {
  element.textContent = text;
  element.dataset.tone = tone;
}

function formatNumber(value) {
  return (Math.abs(value) < 0.005 ? 0 : value).toFixed(2);
}
