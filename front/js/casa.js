
import {
  API_URL,
  PENDING_POLL_MS,
} from "./config.js";

import {
  addTurn,
  log,
} from "./ui.js";


const $ = (id) => document.getElementById(id);

const pendingContainer = $("pending");
const doorState = $("doorState");
const conversation = $("conversation");
const connection = $("connection");
const count = $("count");
const logContainer = $("log");


/* -------------------------------------------------------------------------- */
/* ESTADO                                                                      */
/* -------------------------------------------------------------------------- */

let polling = false;


/* -------------------------------------------------------------------------- */
/* CONEXIÓN                                                                    */
/* -------------------------------------------------------------------------- */

function setBackendStatus(connected) {
  if (!connection) {
    return;
  }

  connection.classList.toggle(
    "online",
    connected
  );

  const label =
    connection.querySelector("span:last-child");

  if (label) {
    label.textContent = connected
      ? "Backend conectado"
      : "Backend sin conexión";
  }
}


/* -------------------------------------------------------------------------- */
/* PETICIONES                                                                  */
/* -------------------------------------------------------------------------- */

function renderPending(items) {
  if (!pendingContainer) {
    return;
  }

  pendingContainer.innerHTML = "";

  if (count) {
    count.textContent = String(items.length);
  }

  if (!items.length) {
    const empty = document.createElement("p");

    empty.className = "empty";
    empty.textContent =
      "No hay peticiones pendientes.";

    pendingContainer.appendChild(empty);

    return;
  }

  items.forEach((request) => {
    const card = document.createElement("article");

    card.className = "request";
    card.dataset.id = request.id;

    const title = document.createElement("strong");

    title.textContent =
      `¿Abrir a ${request.visitante || "visitante"}?`;

    const reason = document.createElement("p");

    reason.textContent =
      request.motivo || "No se ha indicado el motivo.";

    const actions = document.createElement("div");

    actions.className = "actions";

    const approve = document.createElement("button");

    approve.className = "approve";
    approve.type = "button";
    approve.textContent = "Abrir";

    const deny = document.createElement("button");

    deny.type = "button";
    deny.textContent = "Denegar";

    approve.addEventListener(
      "click",
      () => resolveRequest(
        request.id,
        "approve"
      )
    );

    deny.addEventListener(
      "click",
      () => resolveRequest(
        request.id,
        "deny"
      )
    );

    actions.append(
      approve,
      deny
    );

    card.append(
      title,
      reason,
      actions
    );

    pendingContainer.appendChild(card);
  });
}


/* -------------------------------------------------------------------------- */
/* CONSULTAR BACKEND                                                           */
/* -------------------------------------------------------------------------- */

async function poll() {
  if (polling) {
    return;
  }

  polling = true;

  try {
    const response = await fetch(
      `${API_URL}/pending`,
      {
        method: "GET",
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      }
    );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    const items = await response.json();

    setBackendStatus(true);
    renderPending(
      Array.isArray(items) ? items : []
    );

  } catch (error) {
    console.error(
      "Error consultando peticiones:",
      error
    );

    setBackendStatus(false);

  } finally {
    polling = false;
  }
}


/* -------------------------------------------------------------------------- */
/* APROBAR / DENEGAR                                                           */
/* -------------------------------------------------------------------------- */

async function resolveRequest(id, action) {
  const card = pendingContainer?.querySelector(
    `[data-id="${CSS.escape(id)}"]`
  );

  const buttons =
    card?.querySelectorAll("button");

  if (buttons) {
    buttons.forEach(
      (button) => {
        button.disabled = true;
      }
    );
  }

  try {
    const response = await fetch(
      `${API_URL}/pending/${encodeURIComponent(id)}/${action}`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      }
    );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    const result = await response.json();

    if (card) {
      card.remove();
    }

    if (action === "approve") {
      addTurn(
        conversation,
        "system",
        "Apertura autorizada."
      );

      setDoorOpen();

      writeLog(
        `Petición ${id}: apertura autorizada.`
      );

    } else {
      addTurn(
        conversation,
        "system",
        "Entrada denegada."
      );

      writeLog(
        `Petición ${id}: entrada denegada.`
      );
    }

    await poll();

    return result;

  } catch (error) {
    console.error(error);

    writeLog(
      `Error resolviendo ${id}: ${error.message}`
    );

    if (buttons) {
      buttons.forEach(
        (button) => {
          button.disabled = false;
        }
      );
    }
  }
}


/* -------------------------------------------------------------------------- */
/* ESTADO DE PUERTA                                                            */
/* -------------------------------------------------------------------------- */

function setDoorOpen() {
  if (!doorState) {
    return;
  }

  doorState.classList.add("open");
  doorState.textContent = "PUERTA ABIERTA";

  /*
   * Estado visual solamente.
   *
   * La apertura física real de la cerradura
   * deberá conectarse posteriormente al hardware.
   */
  window.setTimeout(
    () => {
      doorState.classList.remove("open");
      doorState.textContent = "PUERTA CERRADA";
    },
    6000
  );
}


/* -------------------------------------------------------------------------- */
/* LOG                                                                         */
/* -------------------------------------------------------------------------- */

function writeLog(message) {
  if (logContainer) {
    log(
      logContainer,
      message
    );
  }
}


/* -------------------------------------------------------------------------- */
/* BOTONES                                                                     */
/* -------------------------------------------------------------------------- */

$("clearConversation")?.addEventListener(
  "click",
  () => {
    if (conversation) {
      conversation.innerHTML = "";
    }
  }
);


$("reload")?.addEventListener(
  "click",
  poll
);


$("test")?.addEventListener(
  "click",
  poll
);


/* -------------------------------------------------------------------------- */
/* INICIO                                                                      */
/* -------------------------------------------------------------------------- */

poll();

window.setInterval(
  poll,
  PENDING_POLL_MS
);
