
/**
 * Cliente WebSocket del videoportero FONA.
 *
 * Servidor -> cliente:
 *   state        {"type": "state", "value": "listening" | "speaking"}
 *   transcript   {"type": "transcript", "role": "visitor" | "assistant" | "system", "content": "..."}
 *   open_door    {"type": "open_door"}
 *   bye          {"type": "bye"}
 *   binario      PCM 16-bit mono 16 kHz
 *
 * Cliente -> servidor:
 *   texto        {"type": "text", "content": "..."}
 *   hangup       {"type": "hangup"}
 *   binario      PCM 16-bit mono 16 kHz
 */

export class PorteroSocket {
  constructor(handlers = {}) {
    this.handlers = handlers;
    this.ws = null;
    this.url = handlers.url || null;
  }

  connect(url = this.url) {
    if (!url) {
      throw new Error("No se ha configurado la URL del WebSocket.");
    }

    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
       this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.url = url;
    this.ws = new WebSocket(url);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      this.handlers.onOpen?.();
    };

    this.ws.onclose = (event) => {
      this.handlers.onClose?.(event);
    };

    this.ws.onerror = (event) => {
      this.handlers.onError?.(event);
    };

    this.ws.onmessage = (event) => {
      this.handlers.onMessage?.(event);
    };
  }

  sendText(content) {
    const text = String(content || "").trim();
    if (!text || !this.isOpen()) {
      return false;
    }

    this.ws.send(
      JSON.stringify({
        type: "text",
        content: text,
      })
    );
    return true;
  }

  sendBytes(data) {
    if (!this.isOpen()) {
      return false;
    }
    this.ws.send(data);
    return true;
  }

  hangup() {
    if (!this.isOpen()) {
      return false;
    }

    try {
      this.ws.send(
        JSON.stringify({
          type: "hangup",
        })
      );
    } catch {
      // Ignorar si ya se estaba cerrando
    }
    return true;
  }

  isOpen() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  close() {
    if (!this.ws) {
      return;
    }

    try {
      this.ws.close();
    } catch {
      // Ignorar si ya estaba cerrado
    }
    this.ws = null;
  }
}