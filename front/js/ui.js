export function addTurn(container, role, text) {
  if (!container || !text) {
    return;
  }

  const element = document.createElement("div");
  element.className = `turn ${role}`;

  const who = document.createElement("div");
  who.className = "who";

  if (role === "visitor") {
    who.textContent = "Visitante";
  } else if (role === "assistant") {
    who.textContent = "Portero";
  } else {
    who.textContent = "Sistema";
  }

  const content = document.createElement("div");
  content.textContent = text;

  element.append(who, content);
  container.append(element);

  container.scrollTop = container.scrollHeight;
}

export function log(container, text) {
  if (!container) {
    return;
  }

  const element = document.createElement("div");

  element.textContent =
    `${new Date().toLocaleTimeString()} ${text}`;

  container.prepend(element);
}