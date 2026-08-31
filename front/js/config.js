// Configuración del backend.
//
// LOCAL:
//   API  -> http://localhost:8080
//   WS   -> ws://localhost:8080/portero
//
// PRODUCCIÓN (Vercel):
//   window.FONA_API_URL
//   window.FONA_WS_URL

const host = window.location.hostname || "localhost";
const defaultApiUrl = `${window.location.protocol === "https:" ? "https:" : "http:"}//${host}:8080`;
const defaultWsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const defaultWsUrl = `${defaultWsProtocol}//${host}:8080/portero`;

export const API_URL = window.FONA_API_URL || defaultApiUrl;
export const WS_URL = window.FONA_WS_URL || defaultWsUrl;
export const PENDING_POLL_MS = 1200;

