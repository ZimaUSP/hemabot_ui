// Pure client-side session state: what the server told us, plus derived UI facts.

import { LinkState, ServerMessageType } from "./protocol.js";

export const initialSession = Object.freeze({
  connected: false,
  clientId: null,
  pilotId: null,
  clients: 0,
  limits: null,
  robotLink: LinkState.OFFLINE,
  robotDetail: "",
});

export function onConnectionOpened(session) {
  return { ...session, connected: true };
}

export function onConnectionClosed(session) {
  // Our id and pilot role die with the socket; the server already stopped the robot.
  return { ...initialSession, limits: session.limits };
}

export function onServerMessage(session, message) {
  switch (message?.type) {
    case ServerMessageType.WELCOME:
      return { ...session, clientId: message.client_id, limits: message.limits };
    case ServerMessageType.STATE:
      return {
        ...session,
        pilotId: message.pilot_id,
        clients: message.clients,
        robotLink: message.robot?.link ?? LinkState.OFFLINE,
        robotDetail: message.robot?.detail ?? "",
      };
    default:
      return session;
  }
}

export function isPilot(session) {
  return session.connected && session.clientId !== null && session.pilotId === session.clientId;
}

export function view(session) {
  const pilot = isPilot(session);
  const otherPilot = session.connected && session.pilotId !== null && !pilot;
  return {
    connected: session.connected,
    isPilot: pilot,
    otherPilot,
    canAcquire: session.connected && session.clientId !== null && session.pilotId === null,
    canStop: session.connected,
    robotLink: session.robotLink,
    clients: session.clients,
    limits: session.limits,
  };
}
