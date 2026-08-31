// Configuración del backend en producción (Render)
const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

export const API_URL = window.FONA_API_URL || (isLocal ? "http://localhost:8080" : "https://fona-1ir2.onrender.com");
export const WS_URL = window.FONA_WS_URL || (isLocal ? "ws://localhost:8080/portero" : "wss://fona-1ir2.onrender.com/portero");
export const PENDING_POLL_MS = 1200;

