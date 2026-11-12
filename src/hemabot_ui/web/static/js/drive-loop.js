// Streams the operator's intent to the server at a fixed rate.
//
// The server stops the robot when drive messages stop arriving, so while the operator
// is moving we must keep sending. When the intent returns to idle we send exactly one
// idle drive message (which halts the robot without giving up control) and go quiet.

export const DRIVE_INTERVAL_MS = 100;

export const IDLE_INTENT = Object.freeze({ linear: 0, angular: 0 });

export const isIdle = (intent) => intent.linear === 0 && intent.angular === 0;

export class DriveLoop {
  #sendDrive;
  #readIntent;
  #intervalMs;
  #timers;
  #timer = null;
  #moving = false;

  /**
   * @param {object} options
   * @param {(intent: {linear: number, angular: number}) => void} options.sendDrive
   * @param {() => {linear: number, angular: number}} options.readIntent
   */
  constructor({ sendDrive, readIntent, intervalMs = DRIVE_INTERVAL_MS, timers = globalThis }) {
    this.#sendDrive = sendDrive;
    this.#readIntent = readIntent;
    this.#intervalMs = intervalMs;
    this.#timers = timers;
  }

  get isMoving() {
    return this.#moving;
  }

  start() {
    if (this.#timer !== null) return;
    this.#timer = this.#timers.setInterval(() => this.tick(), this.#intervalMs);
  }

  stop() {
    if (this.#timer !== null) this.#timers.clearInterval(this.#timer);
    this.#timer = null;
    this.#moving = false;
  }

  /** Forget the moving state, e.g. after the server revoked control or a reconnection. */
  reset() {
    this.#moving = false;
  }

  /** Send immediately instead of waiting for the next interval (for snappy input). */
  tick() {
    const intent = this.#readIntent();
    if (!isIdle(intent)) {
      this.#moving = true;
      this.#sendDrive(intent);
    } else if (this.#moving) {
      this.#moving = false;
      this.#sendDrive(IDLE_INTENT);
    }
  }
}
