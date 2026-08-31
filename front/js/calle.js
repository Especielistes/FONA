
import { WS_URL } from "./config.js";
import { PorteroSocket } from "./websocket.js";
import { addTurn } from "./ui.js";
import { startCamera, createMicrophone } from "./camera.js";
import { SignRecognizer } from "./signs.js";

const $ = (id) => document.getElementById(id);

let socket = null;
let active = false;
let stream = null;
let mic = null;
let currentMode = "voice";
let signRecognizer = null;

// Audio recibido del backend
let audioContext = null;
let audioQueue = [];
let audioPlaying = false;

const video = $("video");
const overlay = $("overlay");
const feed = $("feed");
const liveCaption = $("liveCaption");
const state = $("state");
const connection = $("connection");

const call = $("call");
const hangup = $("hangup");

const signArea = $("signArea");
const textForm = $("textForm");
const textInput = $("textInput");

const signBuffer = $("signBuffer");
const clearSigns = $("clearSigns");
const sendSigns = $("sendSigns");

let signs = [];

/* -------------------------------------------------------------------------- */
/* CONEXIÓN Y ESTADO                                                           */
/* -------------------------------------------------------------------------- */

function setConnection(connected) {
  if (!connection) return;
  connection.classList.toggle("online", connected);
  const label = connection.querySelector("span:last-child");
  if (label) {
    label.textContent = connected ? "Conectado" : "Sin conexión";
  }
}

function setState(text) {
  if (state) {
    state.textContent = text;
  }
}

function setActive(value) {
  active = value;
  if (call) call.disabled = value;
  if (hangup) hangup.disabled = !value;
}

/* -------------------------------------------------------------------------- */
/* AUDIO (REPRODUCCIÓN PCM RECIBIDO DEL BACKEND)                               */
/* -------------------------------------------------------------------------- */

function getAudioContext() {
  if (!audioContext) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioCtx();
  }
  return audioContext;
}

async function playPcm(arrayBuffer) {
  if (!arrayBuffer || arrayBuffer.byteLength === 0) return;

  const context = getAudioContext();
  if (context.state === "suspended") {
    await context.resume();
  }

  // Backend entrega PCM 16-bit mono 16 kHz
  const input = new Int16Array(arrayBuffer);
  const floatData = new Float32Array(input.length);
  for (let i = 0; i < input.length; i++) {
    floatData[i] = input[i] / 32768;
  }

  const buffer = context.createBuffer(1, floatData.length, 16000);
  buffer.copyToChannel(floatData, 0);

  audioQueue.push(buffer);

  if (!audioPlaying) {
    playNextAudio();
  }
}

function playNextAudio() {
  if (!audioQueue.length) {
    audioPlaying = false;
    return;
  }

  audioPlaying = true;
  const context = getAudioContext();
  const buffer = audioQueue.shift();
  const source = context.createBufferSource();

  source.buffer = buffer;
  source.connect(context.destination);

  source.onended = () => {
    playNextAudio();
  };

  source.start();
}

function clearAudio() {
  audioQueue = [];
  audioPlaying = false;
}

/* -------------------------------------------------------------------------- */
/* MODALIDAD                                                                   */
/* -------------------------------------------------------------------------- */

function setMode(modeName) {
  currentMode = modeName;
  document.querySelectorAll(".mode").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === modeName);
  });

  if (signArea) {
    signArea.classList.toggle("hidden", modeName !== "sign");
  }

  if (textForm) {
    textForm.classList.toggle("hidden", modeName !== "text");
  }

  if (modeName === "sign") {
    stopMic(); // Desactivar micrófono al hacer signos
    if (!stream) {
      startCamera(video).then(() => {
        video?.play().catch(() => {});
        signRecognizer?.start();
      });
    } else {
      video?.play().catch(() => {});
      signRecognizer?.start();
    }
  } else {
    signRecognizer?.stop();
  }

  if (modeName === "text") {
    stopMic(); // Desactivar micrófono al escribir
    setTimeout(() => {
      textInput?.focus();
    }, 50);
  }

  if (modeName === "voice" && active) {
    startMic();
  }
}

/* -------------------------------------------------------------------------- */
/* SIGNOS                                                                      */
/* -------------------------------------------------------------------------- */

function renderSigns() {
  if (!signBuffer) return;
  signBuffer.textContent = "";

  if (!signs.length) {
    signBuffer.textContent = "Haz un signo frente a la cámara";
    return;
  }

  signs.forEach((sign) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = sign;
    signBuffer.appendChild(chip);
  });
}

function addDetectedSign(sign) {
  if (!sign) return;
  // Evitar duplicar el mismo signo consecutivamente en el buffer
  if (signs.length > 0 && signs[signs.length - 1] === sign) return;
  signs.push(sign);
  renderSigns();

  if (liveCaption) {
    liveCaption.textContent = `Signo: ${sign}`;
  }
}

async function sendSignsMessage() {
  if (!signs.length) return;

  const content = signs.join(" ");

  if (!socket?.isOpen()) {
    await startConversation();
    setTimeout(() => {
      if (socket?.isOpen()) {
        socket.sendText(content);
        signs = [];
        renderSigns();
      }
    }, 500);
    return;
  }

  socket.sendText(content);
  signs = [];
  renderSigns();
}

/* -------------------------------------------------------------------------- */
/* MENSAJES DEL BACKEND                                                        */
/* -------------------------------------------------------------------------- */

async function handleMessage(event) {
  // 1. Audio binario PCM desde el backend (TTS)
  if (event.data instanceof ArrayBuffer) {
    await playPcm(event.data);
    return;
  }

  // 2. Mensajes JSON de control y transcripción
  if (typeof event.data !== "string") return;

  let payload;
  try {
    payload = JSON.parse(event.data);
  } catch {
    return;
  }

  switch (payload.type) {
    case "transcript": {
      const role = payload.role || "system";
      const content = payload.content || "";
      if (!content) break;

      addTurn(feed, role, content);

      if (liveCaption) {
        liveCaption.textContent = content;
      }
      break;
    }

    case "state": {
      if (payload.value === "speaking") {
        setState("El portero está hablando…");
      } else {
        setState("Escuchando…");
      }
      break;
    }

    case "open_door": {
      addTurn(feed, "system", "Apertura autorizada.");
      if (liveCaption) {
        liveCaption.textContent = "Apertura autorizada. Pase.";
      }
      break;
    }

    case "bye": {
      // Damos un margen para terminar de reproducir el audio en cola
      setTimeout(() => {
        finishConversation();
      }, 1500);
      break;
    }

    default:
      break;
  }
}

/* -------------------------------------------------------------------------- */
/* MICRÓFONO                                                                   */
/* -------------------------------------------------------------------------- */

async function startMic() {
  if (mic) return;
  try {
    mic = await createMicrophone((pcmBuffer) => {
      if (socket && socket.isOpen()) {
        socket.sendBytes(pcmBuffer);
      }
    });
  } catch (err) {
    console.warn("No se pudo iniciar el micrófono:", err);
  }
}

async function stopMic() {
  if (mic) {
    await mic.stop();
    mic = null;
  }
}

/* -------------------------------------------------------------------------- */
/* CICLO DE CONVERSACIÓN                                                       */
/* -------------------------------------------------------------------------- */

let snapshotTimer = null;

async function sendCameraSnapshot() {
  if (!video) return;

  if (video.paused) {
    try {
      await video.play();
    } catch {}
  }

  const width = video.videoWidth || 320;
  const height = video.videoHeight || 240;

  try {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const frameDataUrl = canvas.toDataURL("image/jpeg", 0.4);

    await fetch(`${API_URL}/camera/frame`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: frameDataUrl }),
    });
  } catch (err) {
    console.warn("No se pudo enviar fotograma de cámara:", err);
  }
}

function startFrameSync() {
  sendCameraSnapshot();
  if (!snapshotTimer) {
    snapshotTimer = setInterval(sendCameraSnapshot, 2000);
  }
}

function stopFrameSync() {
  if (snapshotTimer) {
    clearInterval(snapshotTimer);
    snapshotTimer = null;
  }
}

function finishConversation() {
  active = false;
  setConnection(false);
  setActive(false);
  setState("Listo para llamar");

  stopMic();
  stopFrameSync();

  if (socket) {
    socket.close();
    socket = null;
  }
}

async function startConversation() {
  if (active) return;

  try {
    if (!stream) {
      stream = await startCamera(video);
    }

    socket = new PorteroSocket({
      url: WS_URL,
      onOpen: async () => {
        active = true;
        setConnection(true);
        setActive(true);
        setState("En conversación");
        await startMic();
        startFrameSync();
      },
      onClose: () => {
        finishConversation();
      },
      onError: () => {
        setState("Error de conexión");
      },
      onMessage: handleMessage,
    });

    socket.connect();
  } catch (error) {
    console.error(error);
    setConnection(false);
    setActive(false);
    setState(error?.message || "No se ha podido iniciar la conversación.");
  }
}

function hangupConversation() {
  if (socket) {
    socket.hangup();
    socket.close();
    socket = null;
  }
  clearAudio();
  finishConversation();
}

/* -------------------------------------------------------------------------- */
/* EVENTOS                                                                     */
/* -------------------------------------------------------------------------- */

call?.addEventListener("click", startConversation);
hangup?.addEventListener("click", hangupConversation);

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

textForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = textInput?.value?.trim();
  if (!content) return;

  if (!socket?.isOpen()) {
    await startConversation();
    setTimeout(() => {
      if (socket?.isOpen()) {
        socket.sendText(content);
        textInput.value = "";
      }
    }, 500);
    return;
  }

  socket.sendText(content);
  textInput.value = "";
});

clearSigns?.addEventListener("click", () => {
  signs = [];
  renderSigns();
});

sendSigns?.addEventListener("click", sendSignsMessage);

/* -------------------------------------------------------------------------- */
/* INICIALIZACIÓN                                                              */
/* -------------------------------------------------------------------------- */

async function initialize() {
  setConnection(false);
  setActive(false);
  setState("Listo para llamar");
  renderSigns();

  try {
    stream = await startCamera(video);
    startFrameSync();
  } catch {
    // El permiso puede solicitarse al pulsar llamar
  }

  // Inicializar detector de signos con MediaPipe
  signRecognizer = new SignRecognizer({
    video,
    overlay,
    onSign: addDetectedSign,
    onStatus: (msg) => console.log(msg),
  });

  signRecognizer.init();

  setMode("voice");
}

initialize();
