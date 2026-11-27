"use strict";

const selectEl = document.querySelector("#agent-select");
const nameEl = document.querySelector("#agent-name");
const promptEl = document.querySelector("#system-prompt");
const newBtn = document.querySelector("#new-agent");
const configureBtn = document.querySelector("#configure-agent");
const deleteBtn = document.querySelector("#delete-agent");
const editorEl = document.querySelector("#agent-editor");
const saveBtn = document.querySelector("#save-agent");
const cancelBtn = document.querySelector("#cancel-create");
const formStatus = document.querySelector("#form-status");
const analyzeForm = document.querySelector("#analyze-form");
const urlEl = document.querySelector("#page-url");
const runBtn = document.querySelector("#run-agent");
const stopBtn = document.querySelector("#stop-agent");
const runStatus = document.querySelector("#run-status");
const logEl = document.querySelector("#log");
const resultEl = document.querySelector("#result");
const saveReportBtn = document.querySelector("#save-report");

const RESULT_EMPTY = "<p class=\"placeholder\">Итог появится здесь, когда агент закончит.</p>";
const LOG_EMPTY = "<p class=\"placeholder\">Здесь появятся мысли агента и промежуточные действия.</p>";

let creating = false;
let source = null;
let finished = false;
let sawError = false;
let resultRaw = "";
let liveThought = null;

function errorMessage(payload) {
  if (!payload) return "Запрос не выполнен";
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg || "Проверьте поля").join("; ");
  }
  return "Запрос не выполнен";
}

function normalizeUrl(value) {
  const trimmed = value.trim();
  if (!/^https?:\/\//i.test(trimmed)) return `https://${trimmed}`;
  return trimmed;
}

async function loadAgents(selectId) {
  const response = await fetch("/api/agents", { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось получить список агентов");
  const agents = await response.json();
  selectEl.replaceChildren();
  for (const agent of agents) {
    const option = document.createElement("option");
    option.value = String(agent.id);
    option.textContent = agent.name;
    selectEl.appendChild(option);
  }
  const preferred = selectId
    || (agents.find((agent) => agent.name === "SEO-Анализ") || agents[0] || {}).id;
  if (!preferred) {
    nameEl.value = "";
    promptEl.value = "";
    creating = false;
    selectEl.disabled = false;
    setEditorOpen(false);
    formStatus.textContent = "Агентов пока нет. Добавьте первого.";
    syncAgentActions();
    return;
  }
  selectEl.value = String(preferred);
  await loadAgent(preferred);
  setEditorOpen(false);
}

async function loadAgent(id) {
  const response = await fetch(`/api/agents/${id}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось загрузить агента");
  const agent = await response.json();
  nameEl.value = agent.name;
  promptEl.value = agent.system_prompt;
  creating = false;
  selectEl.disabled = false;
  cancelBtn.hidden = true;
  syncAgentActions();
}

function setEditorOpen(open) {
  editorEl.hidden = !open;
}

function syncAgentActions() {
  const hasAgent = Boolean(selectEl.value);
  deleteBtn.disabled = !hasAgent || creating;
}

function startCreate() {
  creating = true;
  selectEl.disabled = true;
  nameEl.value = "";
  promptEl.value = "";
  cancelBtn.hidden = false;
  setEditorOpen(true);
  formStatus.textContent = "Новый агент: укажите имя и системный промт.";
  syncAgentActions();
  nameEl.focus();
}

async function openConfigure() {
  if (!editorEl.hidden) {
    await cancelCreate();
    return;
  }
  if (!selectEl.value) {
    startCreate();
    return;
  }
  await loadAgent(selectEl.value);
  cancelBtn.hidden = false;
  setEditorOpen(true);
  formStatus.textContent = "";
  nameEl.focus();
}

async function cancelCreate() {
  cancelBtn.hidden = true;
  selectEl.disabled = false;
  creating = false;
  formStatus.textContent = "";
  setEditorOpen(false);
  if (selectEl.value) await loadAgent(selectEl.value);
  syncAgentActions();
}

async function saveAgent() {
  const payload = {
    name: nameEl.value.trim(),
    system_prompt: promptEl.value.trim(),
  };
  if (!payload.name || !payload.system_prompt) {
    formStatus.textContent = "Нужны имя и системный промт.";
    return;
  }
  saveBtn.disabled = true;
  formStatus.textContent = "Сохраняю…";
  try {
    const response = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      formStatus.textContent = errorMessage(data);
      return;
    }
    formStatus.textContent = data.action === "updated" ? "Промт обновлён." : "Агент создан.";
    await loadAgents(data.id);
    setEditorOpen(false);
  } catch (error) {
    formStatus.textContent = "Нет связи с сервером.";
  } finally {
    saveBtn.disabled = false;
  }
}

async function deleteAgent() {
  if (!selectEl.value || creating) return;
  const name = selectEl.selectedOptions[0] ? selectEl.selectedOptions[0].textContent : "агента";
  if (!window.confirm(`Удалить агента «${name}»?`)) return;
  deleteBtn.disabled = true;
  try {
    const response = await fetch(`/api/agents/${selectEl.value}`, { method: "DELETE" });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      formStatus.textContent = errorMessage(data);
      return;
    }
    formStatus.textContent = "Агент удалён.";
    setEditorOpen(false);
    await loadAgents();
  } catch (_error) {
    formStatus.textContent = "Нет связи с сервером.";
  } finally {
    syncAgentActions();
  }
}

function clearLog() {
  logEl.innerHTML = LOG_EMPTY;
  liveThought = null;
}

function beginRequestLog(url) {
  liveThought = null;
  const hasHistory = Boolean(logEl.querySelector(".log-line, .log-separator"));
  const placeholder = logEl.querySelector(".placeholder");
  if (placeholder) placeholder.remove();
  if (hasHistory) {
    const separator = document.createElement("div");
    separator.className = "log-separator";
    separator.setAttribute("role", "separator");
    logEl.appendChild(separator);
  }
  const stamp = new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date());
  addLine("status", "Запрос", `${stamp} · ${url}`);
}

function addLine(kind, tag, text) {
  const placeholder = logEl.querySelector(".placeholder");
  if (placeholder) placeholder.remove();
  const line = document.createElement("div");
  line.className = `log-line ${kind}`;
  const tagEl = document.createElement("span");
  tagEl.className = "tag";
  tagEl.textContent = tag;
  const body = document.createElement("span");
  body.className = "body";
  body.textContent = text;
  line.append(tagEl, body);
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
  return body;
}

function appendLog(data) {
  if (!data || !data.type) return;
  if (data.type === "thought_delta") {
    if (!liveThought) liveThought = addLine("thought", "Мысль", "");
    liveThought.textContent += data.text || "";
    logEl.scrollTop = logEl.scrollHeight;
    return;
  }
  if (data.type === "thought_end") {
    liveThought = null;
    return;
  }
  if (data.type === "status") {
    liveThought = null;
    addLine("status", "Ход", data.text || "");
    return;
  }
  if (data.type === "action") {
    liveThought = null;
    addLine("action", "Действие", data.text || "");
    return;
  }
  if (data.type === "observation") {
    addLine("observation", "Данные", data.text || "");
    return;
  }
  if (data.type === "error") {
    sawError = true;
    addLine("error", "Ошибка", data.text || "Ошибка");
  }
}

function resultPlainText() {
  if (resultEl.querySelector(".placeholder")) return "";
  return resultEl.innerText.trim();
}

function syncSaveButton() {
  saveReportBtn.disabled = !resultPlainText();
}

function renderResult() {
  if (!resultRaw.trim()) {
    resultEl.innerHTML = RESULT_EMPTY;
  } else {
    resultEl.innerHTML = renderMarkdown(resultRaw);
    resultEl.scrollTop = resultEl.scrollHeight;
  }
  syncSaveButton();
}

async function saveReport() {
  const text = resultPlainText();
  if (!text) return;
  saveReportBtn.disabled = true;
  try {
    const response = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, title: "Отчет" }),
    });
    if (!response.ok) {
      runStatus.textContent = "Не удалось сохранить отчет.";
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = "Отчет.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  } catch (_error) {
    runStatus.textContent = "Не удалось сохранить отчет.";
  } finally {
    syncSaveButton();
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineFormat(value) {
  return value
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*]+)\*(?=$|[\s).,;:!?])/g, "$1<em>$2</em>");
}

function renderMarkdown(source) {
  const blocks = [];
  const slotted = String(source).replace(/\r\n/g, "\n").replace(/```[^\n`]*\n?([\s\S]*?)```/g, (_, code) => {
    blocks.push(`<pre><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`);
    return `\n@@BLOCK${blocks.length - 1}@@\n`;
  });
  const lines = escapeHtml(slotted).split("\n");
  let html = "";
  let list = null;
  const closeList = () => {
    if (!list) return;
    html += list === "ol" ? "</ol>" : "</ul>";
    list = null;
  };
  for (const line of lines) {
    const block = line.trim().match(/^@@BLOCK(\d+)@@$/);
    if (block) {
      closeList();
      html += blocks[Number(block[1])] || "";
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${inlineFormat(heading[2])}</h${level}>`;
      continue;
    }
    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+\.\s+(.*)$/);
    if (unordered || ordered) {
      const kind = unordered ? "ul" : "ol";
      if (list !== kind) {
        closeList();
        html += kind === "ol" ? "<ol>" : "<ul>";
        list = kind;
      }
      html += `<li>${inlineFormat((unordered || ordered)[1])}</li>`;
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    closeList();
    html += `<p>${inlineFormat(line)}</p>`;
  }
  closeList();
  return html;
}

function setRunning(running) {
  runBtn.disabled = running;
  stopBtn.hidden = !running;
  urlEl.disabled = running;
  runBtn.textContent = running ? "Агент работает…" : "Запустить агента";
}

function stopAnalysis() {
  finished = true;
  if (source) {
    source.close();
    source = null;
  }
  setRunning(false);
  runStatus.textContent = "Остановлено";
}

function startAnalysis() {
  if (creating) {
    runStatus.textContent = "Сначала сохраните нового агента.";
    return;
  }
  if (!selectEl.value) {
    runStatus.textContent = "Выберите агента.";
    return;
  }
  const url = normalizeUrl(urlEl.value);
  if (!url || url === "https://") {
    runStatus.textContent = "Укажите адрес страницы.";
    return;
  }
  urlEl.value = url;
  if (source) source.close();
  finished = false;
  sawError = false;
  resultRaw = "";
  beginRequestLog(url);
  renderResult();
  setRunning(true);
  runStatus.textContent = "Идёт анализ…";
  const agentName = selectEl.selectedOptions[0]?.textContent.trim() || "";
  addLine("status", "Ход", `Подключение к агенту «${agentName}»`);
  const endpoint = `/api/analyze?url=${encodeURIComponent(url)}&agent_id=${encodeURIComponent(selectEl.value)}`;
  source = new EventSource(endpoint);
  source.addEventListener("log", (event) => {
    const data = parseEvent(event);
    if (data) appendLog(data);
  });
  source.addEventListener("result", (event) => {
    const data = parseEvent(event);
    if (!data) return;
    if (typeof data.full === "string") resultRaw = data.full;
    else if (typeof data.delta === "string") resultRaw += data.delta;
    renderResult();
  });
  source.addEventListener("done", () => {
    finished = true;
    source.close();
    source = null;
    setRunning(false);
    runStatus.textContent = sawError ? "Анализ остановился с ошибкой" : "Анализ завершён";
  });
  source.onerror = () => {
    if (finished) return;
    finished = true;
    source.close();
    source = null;
    setRunning(false);
    addLine("error", "Ошибка", "Соединение с сервером прервано");
    runStatus.textContent = "Анализ остановился с ошибкой";
  };
}

function parseEvent(event) {
  try {
    return JSON.parse(event.data);
  } catch (_error) {
    return null;
  }
}

selectEl.addEventListener("change", () => {
  if (selectEl.value) {
    loadAgent(selectEl.value).catch(() => {
      formStatus.textContent = "Не удалось загрузить агента.";
    });
  }
});
newBtn.addEventListener("click", startCreate);
configureBtn.addEventListener("click", () => {
  openConfigure().catch(() => {
    formStatus.textContent = "Не удалось открыть настройки агента.";
  });
});
deleteBtn.addEventListener("click", () => {
  deleteAgent();
});
cancelBtn.addEventListener("click", () => {
  cancelCreate().catch(() => {
    formStatus.textContent = "Не удалось вернуть агента.";
  });
});
saveBtn.addEventListener("click", () => {
  saveAgent();
});
analyzeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  startAnalysis();
});
stopBtn.addEventListener("click", stopAnalysis);
saveReportBtn.addEventListener("click", () => {
  saveReport();
});

const authScreen = document.querySelector("#auth-screen");
const authForm = document.querySelector("#auth-form");
const authTitle = document.querySelector("#auth-title");
const authLead = document.querySelector("#auth-lead");
const authLogin = document.querySelector("#auth-login");
const authPassword = document.querySelector("#auth-password");
const authTerms = document.querySelector("#auth-terms");
const authStatus = document.querySelector("#auth-status");
const authSubmit = document.querySelector("#auth-submit");
const authBack = document.querySelector("#auth-back");
const passwordCancel = document.querySelector("#password-cancel");
const accountButton = document.querySelector("#account-button");
const accountMenu = document.querySelector("#account-menu");
const accountStatus = document.querySelector("#account-status");
const passwordSlot = document.querySelector("#password-slot");
const passwordTemplate = document.querySelector("#password-form-template");
const logoutButton = document.querySelector("#logout-button");

let authMode = "login";

function showAuth(mode) {
  authMode = mode;
  authScreen.hidden = false;
  accountButton.hidden = true;
  accountMenu.hidden = true;
  unmountPasswordForm();
  authTerms.hidden = mode !== "register";
  authBack.hidden = mode !== "register";
  authLead.hidden = mode === "register";
  authTitle.textContent = mode === "register" ? "Регистрация" : "Вход";
  authLead.textContent = "Введите логин и пароль.";
  authSubmit.textContent = mode === "register" ? "Зарегистрироваться" : "Войти";
  authPassword.autocomplete = mode === "register" ? "new-password" : "current-password";
  authPassword.readOnly = true;
}

function unlockPassword(event) {
  event.target.readOnly = false;
}

authPassword.addEventListener("focus", unlockPassword);
authPassword.addEventListener("pointerdown", unlockPassword);

function showApp(login) {
  authScreen.hidden = true;
  accountButton.hidden = false;
  accountButton.textContent = login;
  accountMenu.hidden = true;
  accountStatus.textContent = "";
  unmountPasswordForm();
}

async function enterApp(login) {
  showApp(login);
  clearLog();
  resultRaw = "";
  renderResult();
  await loadAgents();
}

async function loadTerms() {
  try {
    const response = await fetch("/static/terms.md", { cache: "no-store" });
    if (!response.ok) throw new Error("terms");
    authTerms.innerHTML = renderMarkdown(await response.text());
  } catch (_error) {
    authTerms.textContent = "Не удалось загрузить условия использования.";
  }
}

async function boot() {
  await loadTerms();
  const response = await fetch("/api/auth/me", { cache: "no-store" });
  if (!response.ok) {
    showAuth("login");
    return;
  }
  const data = await response.json();
  showApp(data.login);
  await loadAgents();
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authStatus.textContent = "Проверяю пароль…";
  authSubmit.disabled = true;
  authPassword.readOnly = false;
  const payload = { login: authLogin.value.trim(), password: authPassword.value };
  try {
    const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => null);
    if (response.status === 404 && authMode === "login") {
      authStatus.textContent = "";
      showAuth("register");
      return;
    }
    if (!response.ok) {
      authStatus.textContent = errorMessage(data);
      return;
    }
    authPassword.value = "";
    await enterApp(data.login);
  } catch (_error) {
    authStatus.textContent = "Нет связи с сервером.";
  } finally {
    authSubmit.disabled = false;
  }
});

authBack.addEventListener("click", () => {
  authStatus.textContent = "";
  showAuth("login");
});

accountButton.addEventListener("click", () => {
  accountMenu.hidden = !accountMenu.hidden;
  accountStatus.textContent = "";
  if (accountMenu.hidden) unmountPasswordForm();
  else mountPasswordForm();
});

function unmountPasswordForm() {
  passwordSlot.replaceChildren();
}

function mountPasswordForm() {
  if (document.querySelector("#password-form")) return;
  passwordSlot.appendChild(passwordTemplate.content.cloneNode(true));
  document.querySelector("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    accountStatus.textContent = "Меняю пароль…";
    const submit = event.target.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      const response = await fetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: document.querySelector("#current-password").value,
          new_password: document.querySelector("#new-password").value,
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        accountStatus.textContent = errorMessage(data);
        return;
      }
      unmountPasswordForm();
      mountPasswordForm();
      accountStatus.textContent = "Пароль изменён.";
    } catch (_error) {
      accountStatus.textContent = "Нет связи с сервером.";
    } finally {
      const next = document.querySelector("#password-form button[type=submit]");
      if (next) next.disabled = false;
    }
  });
}

passwordCancel.addEventListener("click", () => {
  unmountPasswordForm();
  accountStatus.textContent = "";
  accountMenu.hidden = true;
});

logoutButton.addEventListener("click", async () => {
  if (source) stopAnalysis();
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
  clearLog();
  resultRaw = "";
  renderResult();
  selectEl.innerHTML = "";
  authLogin.value = "";
  authPassword.value = "";
  authStatus.textContent = "";
  showAuth("login");
});

boot().catch(() => {
  showAuth("login");
  authStatus.textContent = "Сервер недоступен.";
});
