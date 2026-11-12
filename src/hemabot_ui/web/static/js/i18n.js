// User facing texts (pt-BR). Server codes are mapped here so the backend stays
// language agnostic.

import { ErrorCode, LinkState } from "./protocol.js";

export const texts = Object.freeze({
  serverConnecting: "Conectando…",
  serverOnline: "Servidor online",
  serverOffline: "Sem conexão",
  robotLink: {
    [LinkState.CONNECTED]: "Robô pronto",
    [LinkState.WAITING]: "Aguardando ROS",
    [LinkState.OFFLINE]: "Robô offline",
  },
  pilot: {
    disconnected: "Sem conexão com o robô. Tentando reconectar…",
    free: "Ninguém está controlando o robô.",
    you: "Você está controlando o robô.",
    other: "Outro usuário está controlando o robô.",
  },
  robotWaitingHint: " O sistema do robô (ROS) ainda não está pronto; ele não vai se mover.",
  lostControl: "Você perdeu o controle do robô.",
  stopped: "Robô parado.",
  confirmTakeover: "Outro usuário está controlando o robô. Tomar o controle dele?",
  errors: {
    [ErrorCode.INVALID_MESSAGE]: "Mensagem inválida enviada ao servidor.",
    [ErrorCode.NOT_PILOT]: "Assuma o controle antes de dirigir.",
    [ErrorCode.PILOT_BUSY]: "Outro usuário já está controlando o robô.",
  },
  unknownError: "Erro inesperado no servidor.",
});
