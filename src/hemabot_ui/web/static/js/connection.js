// WebSocket wrapper with automatic reconnection and JSON framing.
//
// Events (CustomEvent, data in `detail`):
//   "open"     the socket is connected
//   "close"    the socket closed; a reconnection is scheduled
//   "message"  a parsed JSON message from the server

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000];

export class TeleopConnection extends EventTarget {
  #url;
  #WebSocketImpl;
  #reconnectDelays;
  #timers;
  #socket = null;
  #attempt = 0;
  #reconnectTimer = null;
  #closedByUser = false;

  constructor(url, {
    WebSocketImpl = globalThis.WebSocket,
    reconnectDelaysMs = DEFAULT_RECONNECT_DELAYS_MS,
    timers = globalThis,
  } = {}) {
    super();
    this.#url = url;
    this.#WebSocketImpl = WebSocketImpl;
    this.#reconnectDelays = reconnectDelaysMs;
    this.#timers = timers;
  }

  get isOpen() {
    return this.#socket !== null && this.#socket.readyState === this.#WebSocketImpl.OPEN;
  }

  connect() {
    this.#closedByUser = false;
    this.#open();
  }

  close() {
    this.#closedByUser = true;
    this.#timers.clearTimeout(this.#reconnectTimer);
    this.#socket?.close();
  }

  /** Send a JSON-serializable message. Returns false if the socket is not open. */
  send(message) {
    if (!this.isOpen) return false;
    this.#socket.send(JSON.stringify(message));
    return true;
  }

  #open() {
    const socket = new this.#WebSocketImpl(this.#url);
    this.#socket = socket;
    socket.addEventListener("open", () => {
      this.#attempt = 0;
      this.dispatchEvent(new CustomEvent("open"));
    });
    socket.addEventListener("message", (event) => this.#onMessage(event));
    socket.addEventListener("close", () => this.#onClose(socket));
    // "error" is always followed by "close", which handles reconnection.
  }

  #onMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      console.warn("Ignoring malformed server frame", event.data);
      return;
    }
    this.dispatchEvent(new CustomEvent("message", { detail: message }));
  }

  #onClose(socket) {
    if (socket !== this.#socket) return;
    this.#socket = null;
    this.dispatchEvent(new CustomEvent("close"));
    if (this.#closedByUser) return;
    const delays = this.#reconnectDelays;
    const delay = delays[Math.min(this.#attempt, delays.length - 1)];
    this.#attempt += 1;
    this.#reconnectTimer = this.#timers.setTimeout(() => this.#open(), delay);
  }
}
