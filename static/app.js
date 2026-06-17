const cardGrid = document.querySelector("#cardGrid");
const settingsDrawer = document.querySelector("#settingsDrawer");
const settingsToggle = document.querySelector("#settingsToggle");
const themeToggle = document.querySelector("#themeToggle");
const backgroundToggle = document.querySelector("#backgroundToggle");
const credentialGate = document.querySelector("#credentialGate");
const gateUsername = document.querySelector("#gateUsername");
const gatePassword = document.querySelector("#gatePassword");
const credentialState = document.querySelector("#credentialState");
const movieModal = document.querySelector("#movieModal");
const movieForm = document.querySelector("#movieForm");
const modalTitle = document.querySelector("#modalTitle");
const modalCloseButton = document.querySelector("#modalCloseButton");
const confirmModal = document.querySelector("#confirmModal");
const confirmTitle = document.querySelector("#confirmTitle");
const confirmMessage = document.querySelector("#confirmMessage");
const confirmOkButton = document.querySelector("#confirmOkButton");
const confirmCancelButton = document.querySelector("#confirmCancelButton");
const duplicateModal = document.querySelector("#duplicateModal");
const duplicateMessage = document.querySelector("#duplicateMessage");
const duplicateNewTitle = document.querySelector("#duplicateNewTitle");
const duplicateOldTitle = document.querySelector("#duplicateOldTitle");
const duplicateKeepBothButton = document.querySelector("#duplicateKeepBothButton");
const duplicateDeleteOldButton = document.querySelector("#duplicateDeleteOldButton");
const duplicateDeleteNewButton = document.querySelector("#duplicateDeleteNewButton");
const movieAdvanced = document.querySelector("#movieAdvanced");
const movieSubmitLabel = document.querySelector("#movieSubmitLabel");
const metadataButton = document.querySelector("#metadataButton");
const settingsForm = document.querySelector("#settingsForm");
const settingsState = document.querySelector("#settingsState");
const shelfSummary = document.querySelector("#shelfSummary");
const statusLine = document.querySelector("#statusLine");
const checkAllButton = document.querySelector("#checkAllButton");
const runtimePanel = document.querySelector("#runtimePanel");
const runtimeDot = document.querySelector("#runtimeDot");
const runtimeTitle = document.querySelector("#runtimeTitle");
const runtimeSummary = document.querySelector("#runtimeSummary");
const nextCheckTime = document.querySelector("#nextCheckTime");
const nextReminderTime = document.querySelector("#nextReminderTime");
const lastCheckTime = document.querySelector("#lastCheckTime");
const startupActions = document.querySelector("#startupActions");
const startupStatus = document.querySelector("#startupStatus");
const startupInstallButton = document.querySelector("#startupInstallButton");
const updateBadge = document.querySelector("#updateBadge");
const updateText = document.querySelector("#updateText");
const updateButton = document.querySelector("#updateButton");

let state = { items: [], config: {}, runtime: {}, update: {} };
let lastChecks = new Map();
let serverCheckIds = new Set();
let serverQueuedIds = new Set();
let localCheckIds = new Set();
let checkAllRunning = false;
let lastCheckAllSummary = null;
let checkPollTimer = null;
let checkPollDeadline = 0;
let checkPollInFlight = false;
let settingsSaveTimer = null;
let isHydratingSettings = false;
let posterPollTimer = null;
let posterPollDeadline = 0;
let posterPollInFlight = false;
let pendingConfirm = null;
let duplicateCheckQueue = [];
let duplicatePrompting = false;
let duplicateCheckInFlight = false;
let pendingDuplicateResolve = null;
let duplicateInitialSweepDone = false;
let startupInstallInFlight = false;

const POSTER_POLL_INTERVAL_MS = 3000;
const POSTER_POLL_DURATION_MS = 60000;
const CHECK_POLL_INTERVAL_MS = 2000;
const CHECK_POLL_DURATION_MS = 120000;
const UPDATE_POLL_INTERVAL_MS = 30 * 60 * 1000;
const RECENT_METADATA_ATTEMPT_MS = 24 * 60 * 60 * 1000;
const SECRET_PLACEHOLDER = "••••••••••••";
const DUPLICATE_DECISION_PREFIX = "rutrackerDuplicateDecision:v1:";

const sessionId = crypto.randomUUID
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const icons = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  edit: '<path d="m16 3 5 5L8 21H3v-5L16 3Z"/><path d="m14 5 5 5"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
  image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 7.5A9 9 0 1 1 12 3Z"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  power: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  refresh: '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/><path d="M3 12A9 9 0 0 1 18.5 5.8L21 8"/><path d="M21 3v5h-5"/>',
  reset: '<path class="icon-slash" d="M4.5 18.5 19.5 5.5"/><text class="icon-text" x="12" y="12.5" text-anchor="middle">NEW</text>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  settings: '<path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 1 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1A2 2 0 1 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 1 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
};

function icon(name) {
  return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ""}</svg>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = icon(node.dataset.icon);
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Запрос не выполнен");
  }
  return payload;
}

function setBusy(button, busy, text) {
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle("is-checking", busy);
  if (busy && text) {
    button.dataset.originalHtml ||= button.innerHTML;
    button.textContent = text;
  }
  if (!busy && button.dataset.originalHtml) {
    button.innerHTML = button.dataset.originalHtml;
    delete button.dataset.originalHtml;
    hydrateIcons(button);
  }
}

function numberSet(values = []) {
  return new Set(values.map((value) => Number(value)).filter(Number.isFinite));
}

function isItemChecking(itemId) {
  const id = Number(itemId);
  return serverCheckIds.has(id) || localCheckIds.has(id);
}

function isItemQueued(itemId) {
  return serverQueuedIds.has(Number(itemId));
}

function hasPendingChecks() {
  return serverCheckIds.size > 0 || serverQueuedIds.size > 0;
}

function syncCheckPayload(payload = {}) {
  for (const result of payload.check_results || []) {
    rememberCheck(result);
  }
  if (payload.check_all_summary) {
    rememberCheckAllSummary(payload.check_all_summary);
  }
  if ("check_all_running" in payload) {
    checkAllRunning = Boolean(payload.check_all_running);
  }
  serverCheckIds = numberSet(payload.checking_item_ids || []);
  serverQueuedIds = numberSet(payload.queued_item_ids || []);
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function hasRecentMetadataAttempt(item) {
  const date = parseDate(item?.poster_updated_at);
  return Boolean(date && Date.now() - date.getTime() < RECENT_METADATA_ATTEMPT_MS);
}

function needsPosterPolling() {
  return (state.items || []).some((item) => {
    const needsPoster = !item.poster_url && !hasRecentMetadataAttempt(item);
    const needsSearchSync = Boolean(
      item.sync_search_from_imdb && item.imdb_url && !item.imdb_search_synced_at
    );
    return needsPoster || needsSearchSync;
  });
}

function formatClock(value) {
  const date = parseDate(value);
  if (!date) return "-";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRelative(value) {
  const date = parseDate(value);
  if (!date) return "-";
  const deltaSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  const absSeconds = Math.abs(deltaSeconds);
  if (absSeconds < 45) return deltaSeconds >= 0 ? "сейчас" : "только что";
  const minutes = Math.round(absSeconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  let text;
  if (days > 0) {
    text = `${days} д ${hours % 24} ч`;
  } else if (hours > 0) {
    text = `${hours} ч ${minutes % 60} м`;
  } else {
    text = `${minutes} м`;
  }
  return deltaSeconds >= 0 ? `через ${text}` : `${text} назад`;
}

function pluralRu(count, one, few, many) {
  const value = Math.abs(Number(count) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function applyTheme(theme = localStorage.getItem("theme") || "dark") {
  document.body.classList.toggle("light", theme === "light");
  localStorage.setItem("theme", theme);
  const nextIcon = theme === "light" ? "moon" : "sun";
  themeToggle.innerHTML = icon(nextIcon);
  themeToggle.title = theme === "light" ? "Темная тема" : "Светлая тема";
}

function posterFallback(title) {
  const words = String(title || "Movie").trim();
  const wrapper = document.createElement("div");
  wrapper.className = "fallback-poster";
  const text = document.createElement("strong");
  const length = words.length;
  const fontSize = length > 58 ? 15 : length > 42 ? 17 : length > 28 ? 19 : 23;
  text.style.setProperty("--fallback-font", `${fontSize}px`);
  text.textContent = words || "Movie";
  wrapper.append(text);
  return wrapper;
}

function hasCredentials() {
  const config = state.config || {};
  return Boolean(String(config.rutracker_username || "").trim() && config.has_rutracker_password);
}

function setSettingsStatus(message, isError = false) {
  settingsState.textContent = message;
  settingsState.classList.toggle("error", isError);
  credentialState.textContent = message;
  credentialState.classList.toggle("error", isError);
}

function focusCredentialGate() {
  credentialGate.hidden = false;
  credentialGate.classList.add("attention");
  setTimeout(() => credentialGate.classList.remove("attention"), 520);
  const target = gateUsername.value.trim() ? gatePassword : gateUsername;
  target.focus();
}

function applySettingsToForms() {
  const config = state.config || {};
  statusLine.textContent = `Автопроверка каждые ${config.check_interval_minutes || 0} мин`;
  setSettingsStatus(
    hasCredentials() ? "RuTracker сохранен · autosave включен" : "Введите RuTracker логин и пароль"
  );
  isHydratingSettings = true;
  settingsForm.rutracker_username.value = config.rutracker_username || "";
  settingsForm.rutracker_password.value = "";
  settingsForm.rutracker_password.placeholder = config.has_rutracker_password
    ? SECRET_PLACEHOLDER
    : "Обязательно";
  settingsForm.default_min_seeders.value = config.default_min_seeders ?? 5;
  settingsForm.default_min_size_gb.value = config.default_min_size_gb ?? 5;
  settingsForm.default_require_1080p.checked = Boolean(config.default_require_1080p);
  backgroundToggle.checked = Boolean(config.background_enabled);
  settingsForm.check_interval_minutes.value = config.check_interval_minutes ?? 360;
  settingsForm.reminder_interval_hours.value = config.reminder_interval_hours ?? 12;
  settingsForm.max_search_pages.value = config.max_search_pages ?? 3;
  if (document.activeElement !== gateUsername) {
    gateUsername.value = config.rutracker_username || "";
  }
  if (document.activeElement !== gatePassword) {
    gatePassword.value = "";
  }
  gatePassword.placeholder = config.has_rutracker_password
    ? SECRET_PLACEHOLDER
    : "Обязательно";
  credentialGate.hidden = hasCredentials();
  isHydratingSettings = false;
}

function renderRuntime() {
  const runtime = state.runtime || {};
  if (startupInstallInFlight && runtime.startup_installed) {
    startupInstallInFlight = false;
    setBusy(startupInstallButton, false);
  }
  runtimePanel.classList.remove("running", "paused", "stale", "startup-missing");
  if (startupActions && startupStatus && startupInstallButton) {
    startupActions.hidden = true;
    startupStatus.classList.remove("error");
    startupInstallButton.hidden = true;
  }

  if (!runtime.background_enabled) {
    runtimePanel.classList.add("paused");
    runtimeTitle.textContent = "Только вручную";
    runtimeSummary.textContent = "Фоновая проверка выключена, ручные проверки работают.";
  } else if (runtime.background_running) {
    runtimePanel.classList.add("running");
    runtimeTitle.textContent = "Фон работает";
    const pendingItems = runtime.pending_new_item_count || 0;
    runtimeSummary.textContent = `${pendingItems} ${pluralRu(pendingItems, "фильм", "фильма", "фильмов")} с NEW ждут просмотра.`;
  } else {
    runtimePanel.classList.add("stale");
    runtimeTitle.textContent = "Фон не найден";
    runtimeSummary.textContent = "Запустите фоновой чекер или переустановите автозапуск.";
  }

  if (runtime.background_enabled && !runtime.startup_installed && startupActions && startupStatus && startupInstallButton) {
    runtimePanel.classList.add("startup-missing");
    startupActions.hidden = false;
    startupStatus.textContent = runtime.startup_status_message || "После перезагрузки фон не запустится.";
    startupInstallButton.hidden = !runtime.startup_supported;
    startupInstallButton.disabled = startupInstallInFlight;
    startupStatus.classList.toggle("error", !runtime.startup_supported);
  }

  runtimeDot.title = runtimeTitle.textContent;
  if (!runtime.background_enabled) {
    nextCheckTime.textContent = "вручную";
    nextReminderTime.textContent = "вручную";
  } else {
    nextCheckTime.textContent = runtime.next_check_at
      ? `${formatRelative(runtime.next_check_at)} (${formatClock(runtime.next_check_at)})`
      : "-";
    nextReminderTime.textContent = runtime.next_reminder_at
      ? `${formatRelative(runtime.next_reminder_at)} (${formatClock(runtime.next_reminder_at)})`
      : runtime.pending_new_count > 0 && runtime.reminder_interval_hours <= 0
        ? "выключено"
        : "-";
  }
  lastCheckTime.textContent = runtime.last_check_at
    ? `${formatRelative(runtime.last_check_at)} (${formatClock(runtime.last_check_at)})`
    : "-";
}

async function installStartup() {
  if (startupInstallInFlight || !startupInstallButton || !startupStatus) return;
  startupInstallInFlight = true;
  startupStatus.classList.remove("error");
  startupStatus.textContent = "Добавляем в автозагрузку...";
  setBusy(startupInstallButton, true);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 12000);
  try {
    const payload = await api("/api/startup/install", {
      method: "POST",
      signal: controller.signal,
    });
    state.runtime = payload.runtime || await api("/api/runtime");
    renderRuntime();
  } catch (error) {
    const message = error.name === "AbortError"
      ? "операция заняла слишком много времени"
      : error.message;
    startupStatus.textContent = `Не удалось включить автозагрузку: ${message}`;
    startupStatus.classList.add("error");
    if (startupActions) startupActions.hidden = false;
    startupInstallButton.hidden = false;
  } finally {
    clearTimeout(timeoutId);
    startupInstallInFlight = false;
    setBusy(startupInstallButton, false);
  }
}

function renderUpdateStatus() {
  const update = state.update || {};
  if (!updateBadge || !updateText || !updateButton) return;

  const quietStates = new Set(["", "up_to_date", "local_ahead", "local_diverged"]);
  const stateName = update.state || "";
  const shouldShow = !quietStates.has(stateName);
  updateBadge.hidden = !shouldShow;
  updateBadge.classList.toggle("available", stateName === "update_available");
  updateBadge.classList.toggle("blocked", stateName.startsWith("blocked_"));
  updateBadge.classList.toggle("error", stateName === "error" || stateName === "git_missing" || stateName === "no_git_repo");

  updateText.textContent = update.message || "Проверяем обновления...";
  updateButton.hidden = !update.can_apply;
  updateButton.disabled = !update.can_apply;
}

function renderCards() {
  cardGrid.innerHTML = "";
  shelfSummary.textContent = state.items.length
    ? `${state.items.length} карточек · ${state.items.reduce((sum, item) => sum + Number(item.new_count || 0), 0)} новых`
    : "Добавьте первый поиск или выберите карточку для открытия RuTracker.";

  const add = document.createElement("button");
  const locked = !hasCredentials();
  add.className = `add-card ${locked ? "locked" : ""}`.trim();
  add.type = "button";
  add.setAttribute("aria-disabled", String(locked));
  add.innerHTML = `
    <span class="add-card-inner">
      <span class="add-plus">${icon("plus")}</span>
      <strong>${locked ? "Сначала войдите" : "Добавить фильм"}</strong>
      <span>${locked ? "Нужны логин и пароль RuTracker" : "Новый поиск RuTracker"}</span>
    </span>
  `;
  add.addEventListener("click", () => {
    if (locked) {
      focusCredentialGate();
      return;
    }
    openMovieModal();
  });
  cardGrid.append(add);

  for (const item of state.items) {
    cardGrid.append(createMovieCard(item));
  }
}

function createMovieCard(item) {
  const card = document.createElement("article");
  const checking = isItemChecking(item.id);
  const queued = isItemQueued(item.id);
  card.className = `movie-card ${checking ? "is-card-checking" : ""} ${queued ? "is-card-queued" : ""}`.trim();

  const main = document.createElement("button");
  main.type = "button";
  main.className = "card-main";
  main.title = "Открыть поиск RuTracker";
  main.addEventListener("click", () => {
    window.open(item.search_url, "_blank", "noreferrer");
  });

  const poster = document.createElement("div");
  poster.className = "poster";
  if (item.poster_url) {
    const img = document.createElement("img");
    img.src = item.poster_url;
    img.alt = item.title || item.query;
    img.loading = "lazy";
    img.addEventListener("error", () => {
      img.remove();
      poster.append(posterFallback(item.title || item.query));
    }, { once: true });
    poster.append(img);
  } else {
    poster.append(posterFallback(item.title || item.query));
  }

  if (Number(item.new_count || 0) > 0) {
    const badge = document.createElement("span");
    badge.className = "new-badge";
    badge.textContent = `${item.new_count} NEW`;
    poster.append(badge);
  }

  const copy = document.createElement("div");
  copy.className = "card-copy";
  const title = document.createElement("h3");
  title.textContent = item.title || item.query;
  const meta = document.createElement("div");
  meta.className = "card-meta";
  for (const text of [
    `${item.min_seeders}+ сидов`,
    `${item.min_size_gb}+ GB`,
    item.require_1080p ? "1080p+" : "любое",
  ]) {
    const chip = document.createElement("span");
    chip.textContent = text;
    meta.append(chip);
  }
  const lastCheck = lastChecks.get(item.id);
  if (checking) {
    const chip = document.createElement("span");
    chip.className = "state-chip checking-chip";
    chip.textContent = "проверяем";
    meta.append(chip);
  } else if (queued) {
    const chip = document.createElement("span");
    chip.className = "state-chip queued-chip";
    chip.textContent = "в очереди";
    meta.append(chip);
  } else if (lastCheck) {
    const chip = document.createElement("span");
    chip.className = `state-chip ${lastCheck.error ? "error-chip" : "checked-chip"}`;
    chip.textContent = lastCheck.error ? "ошибка" : "проверено";
    meta.append(chip);
  }
  copy.append(title, meta);
  main.append(poster, copy);

  const actions = document.createElement("div");
  actions.className = "card-actions";
  actions.append(
    cardButton("edit", "Редактировать", () => openMovieModal(item)),
    cardButton("refresh", "Проверить", () => checkItem(item)),
    cardButton("reset", "Сбросить NEW", () => resetNew(item), Number(item.new_count || 0) <= 0, "reset-new-button"),
    cardButton("external", "IMDb", () => window.open(item.imdb_url, "_blank", "noreferrer"), !item.imdb_url),
    cardButton("trash", "Удалить", () => deleteItem(item), false, "danger-button"),
  );

  if (checking || queued) {
    const refreshButton = actions.querySelector("button:nth-child(2)");
    if (refreshButton) {
      refreshButton.disabled = true;
      refreshButton.classList.toggle("is-checking", checking);
    }
  }

  card.append(main, actions);
  return card;
}

function cardButton(iconName, title, onClick, disabled = false, extraClass = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `icon-button ${extraClass}`.trim();
  button.title = title;
  button.ariaLabel = title;
  button.disabled = disabled;
  button.innerHTML = icon(iconName);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

function render() {
  applySettingsToForms();
  renderRuntime();
  renderUpdateStatus();
  renderCheckAllButton();
  renderCards();
}

function openMovieModal(item = null) {
  if (!item && !hasCredentials()) {
    focusCredentialGate();
    return;
  }
  const config = state.config || {};
  const fields = movieForm.elements;
  movieForm.reset();
  fields.id.value = item?.id || "";
  fields.title.value = item?.title || "";
  fields.query.value = item?.query || "";
  fields.imdb_url.value = item?.imdb_url || "";
  fields.poster_url.value = item?.poster_url || "";
  fields.min_seeders.value = item?.min_seeders ?? config.default_min_seeders ?? 5;
  fields.min_size_gb.value = item?.min_size_gb ?? config.default_min_size_gb ?? 5;
  fields.require_1080p.checked = item
    ? Boolean(item.require_1080p)
    : Boolean(config.default_require_1080p ?? true);
  fields.sync_search_from_imdb.checked = item
    ? Boolean(item.sync_search_from_imdb)
    : true;
  modalTitle.textContent = item ? "Редактировать фильм" : "Новый фильм";
  movieSubmitLabel.textContent = item ? "Сохранить" : "Добавить";
  movieAdvanced.open = Boolean(item);
  metadataButton.hidden = !item;
  metadataButton.parentElement.hidden = !item;
  movieModal.hidden = false;
  setTimeout(() => fields.query.focus(), 0);
}

function closeMovieModal() {
  movieModal.hidden = true;
}

function closeConfirmModal(result = false) {
  if (confirmModal.hidden) return;
  confirmModal.hidden = true;
  const resolver = pendingConfirm;
  pendingConfirm = null;
  if (resolver) {
    resolver(Boolean(result));
  }
}

function showConfirmDialog({ title, message, confirmLabel = "Удалить" }) {
  if (pendingConfirm) {
    closeConfirmModal(false);
  }
  confirmTitle.textContent = title;
  confirmMessage.textContent = message;
  confirmOkButton.textContent = confirmLabel;
  confirmModal.hidden = false;
  setTimeout(() => confirmCancelButton.focus(), 0);
  return new Promise((resolve) => {
    pendingConfirm = resolve;
  });
}

function duplicateDecisionKey(leftId, rightId) {
  const ids = [Number(leftId), Number(rightId)].sort((a, b) => a - b);
  return `${DUPLICATE_DECISION_PREFIX}${ids[0]}:${ids[1]}`;
}

function hasDuplicateDecision(leftId, rightId) {
  return Boolean(localStorage.getItem(duplicateDecisionKey(leftId, rightId)));
}

function rememberDuplicateDecision(leftId, rightId) {
  localStorage.setItem(duplicateDecisionKey(leftId, rightId), String(Date.now()));
}

function itemDisplayName(item) {
  return item?.title || item?.query || `Карточка #${item?.id || ""}`;
}

function closeDuplicateModal(action = "keep") {
  if (duplicateModal.hidden) return;
  duplicateModal.hidden = true;
  const resolver = pendingDuplicateResolve;
  pendingDuplicateResolve = null;
  if (resolver) {
    resolver(action);
  }
}

function showDuplicateDialog(newItem, oldItem) {
  duplicateMessage.textContent = "Карточки похожи по IMDb или строке поиска. Проверьте, это не один и тот же фильм?";
  duplicateNewTitle.textContent = itemDisplayName(newItem);
  duplicateOldTitle.textContent = itemDisplayName(oldItem);
  duplicateModal.hidden = false;
  setTimeout(() => duplicateKeepBothButton.focus(), 0);
  return new Promise((resolve) => {
    pendingDuplicateResolve = resolve;
  });
}

async function handleDuplicateCandidate(item, candidate) {
  const other = candidate.item;
  if (!item?.id || !other?.id || hasDuplicateDecision(item.id, other.id)) return;
  const newItem = Number(item.id) >= Number(other.id) ? item : other;
  const oldItem = Number(item.id) >= Number(other.id) ? other : item;

  duplicatePrompting = true;
  try {
    const action = await showDuplicateDialog(newItem, oldItem);
    rememberDuplicateDecision(item.id, other.id);
    if (action === "delete-new") {
      await api(`/api/items/${newItem.id}`, { method: "DELETE" });
      await load();
    } else if (action === "delete-old") {
      await api(`/api/items/${oldItem.id}`, { method: "DELETE" });
      await load();
    }
  } finally {
    duplicatePrompting = false;
    runDuplicateCheckQueue();
  }
}

async function checkItemDuplicates(itemId) {
  if (!itemId) return;
  try {
    const payload = await api(`/api/items/${itemId}/duplicates`);
    const item = payload.item;
    const candidate = (payload.candidates || [])
      .find((entry) => entry?.item?.id && !hasDuplicateDecision(item.id, entry.item.id));
    if (candidate) {
      await handleDuplicateCandidate(item, candidate);
    }
  } catch (error) {
    // Duplicate prompts are advisory; failed checks should not block the main flow.
  }
}

function queueDuplicateCheck(itemId) {
  const id = Number(itemId);
  if (!id || duplicateCheckQueue.includes(id)) return;
  duplicateCheckQueue.push(id);
  runDuplicateCheckQueue();
}

function queueDuplicateChecksForItems(items = []) {
  for (const item of items) {
    queueDuplicateCheck(item.id);
  }
}

async function runDuplicateCheckQueue() {
  if (duplicatePrompting || duplicateCheckInFlight || duplicateCheckQueue.length === 0) return;
  const itemId = duplicateCheckQueue.shift();
  duplicateCheckInFlight = true;
  try {
    await checkItemDuplicates(itemId);
  } finally {
    duplicateCheckInFlight = false;
  }
  if (!duplicatePrompting && !duplicateCheckInFlight && duplicateCheckQueue.length > 0) {
    runDuplicateCheckQueue();
  }
}

async function saveMovie(event) {
  event.preventDefault();
  if (!movieForm.elements.id.value && !hasCredentials()) {
    focusCredentialGate();
    statusLine.textContent = "Сначала введите логин и пароль RuTracker.";
    return;
  }
  const submitButton = movieForm.querySelector("button[type='submit']");
  setBusy(submitButton, true, "Сохраняем");
  try {
    const data = Object.fromEntries(new FormData(movieForm).entries());
    const id = data.id;
    delete data.id;
    data.title = String(data.title || data.query || "").trim();
    data.query = String(data.query || data.title || "").trim();
    data.imdb_url = String(data.imdb_url || "").trim();
    data.poster_url = String(data.poster_url || "").trim();
    data.min_seeders = Number(data.min_seeders || 0);
    data.min_size_gb = Number(data.min_size_gb || 0);
    data.require_1080p = movieForm.elements.require_1080p.checked;
    data.sync_search_from_imdb = movieForm.elements.sync_search_from_imdb.checked;
    data.enabled = true;

    const item = id
      ? await api(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(data) })
      : await api("/api/items", { method: "POST", body: JSON.stringify(data) });
    if (!id && item.initial_check_started) {
      serverCheckIds.add(Number(item.id));
    }
    closeMovieModal();
    await load();
    queueDuplicateCheck(item.id);
    if (!id && item.initial_check_started) {
      startCheckPolling();
    }
    if (!data.poster_url) {
      refreshMetadata(item.id);
    }
  } catch (error) {
    statusLine.textContent = `Не удалось сохранить: ${error.message}`;
  } finally {
    setBusy(submitButton, false);
  }
}

async function refreshMetadata(itemId = movieForm.elements.id.value) {
  if (!itemId) {
    statusLine.textContent = "Сначала сохраните карточку, потом обновите данные IMDb.";
    return;
  }
  statusLine.textContent = "Ищем данные на IMDb...";
  try {
    const payload = await api(`/api/items/${itemId}/refresh-metadata`, { method: "POST" });
    await load();
    queueDuplicateCheck(payload.item?.id || itemId);
    statusLine.textContent = payload.metadata_error
      ? "Данные IMDb не найдены, оставили текущие значения."
      : "Данные IMDb обновлены.";
  } catch (error) {
    statusLine.textContent = `Данные IMDb не обновились: ${error.message}`;
  }
}

async function checkItem(item) {
  const itemId = Number(item.id);
  localCheckIds.add(itemId);
  renderCards();
  statusLine.textContent = `Проверяем: ${item.title || item.query}`;
  try {
    const result = await api(`/api/items/${item.id}/check`, { method: "POST" });
    rememberCheck(result);
    await load();
    statusLine.textContent = result.error
      ? `Ошибка проверки: ${result.error}`
      : `Проверка: ${result.raw || 0} найдено, ${result.matched || 0} подходит, ${result.new || 0} новых.`;
  } catch (error) {
    lastChecks.set(item.id, { error: true, message: error.message });
    statusLine.textContent = `Ошибка проверки: ${error.message}`;
  } finally {
    localCheckIds.delete(itemId);
    renderCards();
  }
}

async function resetNew(item) {
  await api(`/api/items/${item.id}/reset-new`, { method: "POST" });
  await load();
}

async function deleteItem(item) {
  const title = item.title || item.query;
  const confirmed = await showConfirmDialog({
    title: "Удалить карточку?",
    message: `«${title}» будет удален из отслеживания вместе с найденными результатами.`,
    confirmLabel: "Удалить",
  });
  if (!confirmed) return;
  await api(`/api/items/${item.id}`, { method: "DELETE" });
  await load();
}

function rememberCheck(result) {
  if (!result || !result.item) return;
  lastChecks.set(result.item.id, {
    error: Boolean(result.error),
    message: result.error
      ? `Ошибка: ${result.error}`
      : `${result.raw || 0} найдено, ${result.matched || 0} подходит, ${result.new || 0} новых.`,
  });
}

function rememberCheckAllSummary(summary) {
  if (!summary) return;
  lastCheckAllSummary = summary;
  for (const result of summary.results || []) {
    rememberCheck(result);
    if (result.error && result.item) {
      lastChecks.set(result.item.id, { error: true, message: result.error });
    }
  }
}

function formatCheckAllSummary(summary) {
  const pendingItems = summary.total_pending_new_item_count ?? (summary.results || [])
    .filter((result) => Number(result.pending_new || 0) > 0).length;
  return `Готово: проверено ${summary.items_checked || 0}; за проверку ${summary.total_new || 0} NEW; с NEW ${pendingItems} ${pluralRu(pendingItems, "фильм", "фильма", "фильмов")}.`;
}

function renderCheckAllButton() {
  setBusy(checkAllButton, checkAllRunning);
}

async function load() {
  const [itemsPayload, runtimePayload, updatePayload] = await Promise.all([
    api("/api/items"),
    api("/api/runtime"),
    api("/api/update/status").catch((error) => ({
      state: "error",
      message: `Не удалось проверить обновления: ${error.message}`,
    })),
  ]);
  syncCheckPayload(itemsPayload);
  state = { ...itemsPayload, runtime: runtimePayload, update: updatePayload };
  render();
  if (!duplicateInitialSweepDone) {
    duplicateInitialSweepDone = true;
    queueDuplicateChecksForItems(state.items || []);
  }
  startPosterPolling();
  startCheckPolling();
}

function stopCheckPolling() {
  if (checkPollTimer) {
    clearInterval(checkPollTimer);
    checkPollTimer = null;
  }
  checkPollDeadline = 0;
  checkPollInFlight = false;
}

async function refreshItemsForChecks() {
  if (checkPollInFlight) return;
  if (!checkAllRunning && (Date.now() >= checkPollDeadline || !hasPendingChecks())) {
    stopCheckPolling();
    return;
  }

  checkPollInFlight = true;
  const wasCheckAllRunning = checkAllRunning;
  try {
    const itemsPayload = await api("/api/items");
    syncCheckPayload(itemsPayload);
    state = {
      ...state,
      items: itemsPayload.items || [],
      config: itemsPayload.config || state.config,
    };
    renderCheckAllButton();
    renderCards();
    if (wasCheckAllRunning && !checkAllRunning && lastCheckAllSummary) {
      statusLine.textContent = formatCheckAllSummary(lastCheckAllSummary);
    }
    if (!checkAllRunning && !hasPendingChecks()) {
      stopCheckPolling();
    }
  } catch (error) {
    stopCheckPolling();
  } finally {
    checkPollInFlight = false;
  }
}

function startCheckPolling() {
  if (!checkAllRunning && !hasPendingChecks()) return;
  checkPollDeadline = Date.now() + CHECK_POLL_DURATION_MS;
  if (checkPollTimer) return;
  checkPollTimer = setInterval(refreshItemsForChecks, CHECK_POLL_INTERVAL_MS);
  refreshItemsForChecks();
}

function stopPosterPolling() {
  if (posterPollTimer) {
    clearInterval(posterPollTimer);
    posterPollTimer = null;
  }
  posterPollDeadline = 0;
  posterPollInFlight = false;
}

async function refreshItemsForPosters() {
  if (posterPollInFlight) return;
  if (Date.now() >= posterPollDeadline || !needsPosterPolling()) {
    stopPosterPolling();
    return;
  }

  posterPollInFlight = true;
  try {
    const previousItems = new Map((state.items || []).map((item) => [Number(item.id), item]));
    const itemsPayload = await api("/api/items");
    syncCheckPayload(itemsPayload);
    const changedItems = (itemsPayload.items || []).filter((item) => {
      const previous = previousItems.get(Number(item.id));
      return previous && (
        previous.title !== item.title ||
        previous.query !== item.query ||
        previous.imdb_url !== item.imdb_url
      );
    });
    state = {
      ...state,
      items: itemsPayload.items || [],
      config: itemsPayload.config || state.config,
    };
    renderCards();
    queueDuplicateChecksForItems(changedItems);
    if (!needsPosterPolling()) {
      stopPosterPolling();
    }
  } catch (error) {
    stopPosterPolling();
  } finally {
    posterPollInFlight = false;
  }
}

function startPosterPolling() {
  if (posterPollTimer || !needsPosterPolling()) return;
  posterPollDeadline = Date.now() + POSTER_POLL_DURATION_MS;
  posterPollTimer = setInterval(refreshItemsForPosters, POSTER_POLL_INTERVAL_MS);
  refreshItemsForPosters();
}

async function refreshRuntime() {
  try {
    state.runtime = await api("/api/runtime");
    renderRuntime();
  } catch (error) {
    runtimePanel.classList.remove("running", "paused");
    runtimePanel.classList.add("stale");
    runtimeTitle.textContent = "Статус недоступен";
    runtimeSummary.textContent = error.message;
  }
}

async function refreshUpdateStatus(force = false) {
  try {
    state.update = await api(`/api/update/status${force ? "?force=1" : ""}`);
  } catch (error) {
    state.update = {
      state: "error",
      message: `Не удалось проверить обновления: ${error.message}`,
    };
  }
  renderUpdateStatus();
}

async function waitForRestartAndReload() {
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`/api/health?restart=${Date.now()}`, { cache: "no-store" });
      if (response.ok) {
        window.location.reload();
        return;
      }
    } catch (error) {
      // Server is expected to disappear briefly while the update restarts it.
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  state.update = {
    state: "error",
    message: "Обновление установлено, но приложение не перезапустилось автоматически.",
  };
  renderUpdateStatus();
}

async function applyUpdate() {
  setBusy(updateButton, true, "Обновляем...");
  try {
    const payload = await api("/api/update/apply", { method: "POST" });
    state.update = {
      ...(payload.status || {}),
      state: "restarting",
      message: payload.message || "Обновление установлено. Перезапускаем...",
    };
    renderUpdateStatus();
    await waitForRestartAndReload();
  } catch (error) {
    state.update = {
      state: "error",
      message: `Обновление не установлено: ${error.message}`,
    };
    renderUpdateStatus();
  } finally {
    setBusy(updateButton, false);
  }
}

function collectSettingsPayload() {
  const data = {
    rutracker_username: settingsForm.rutracker_username.value.trim(),
    default_min_seeders: Number(settingsForm.default_min_seeders.value || 0),
    default_min_size_gb: Number(settingsForm.default_min_size_gb.value || 0),
    default_require_1080p: settingsForm.default_require_1080p.checked,
    background_enabled: backgroundToggle.checked,
    check_interval_minutes: Number(settingsForm.check_interval_minutes.value || 0),
    reminder_interval_hours: Number(settingsForm.reminder_interval_hours.value || 0),
    max_search_pages: Number(settingsForm.max_search_pages.value || 3),
  };
  if (settingsForm.rutracker_password.value.trim()) {
    data.rutracker_password = settingsForm.rutracker_password.value;
  }
  return data;
}

async function saveSettings(payload = collectSettingsPayload()) {
  setSettingsStatus("Сохраняем...");
  try {
    const updated = await api("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
    state.config = { ...state.config, ...updated };
    if (typeof payload.background_enabled !== "undefined") {
      backgroundToggle.checked = Boolean(updated.background_enabled);
      await refreshRuntime();
    }
    applySettingsToForms();
    renderCards();
    setSettingsStatus(hasCredentials() ? "Сохранено" : "Введите RuTracker логин и пароль");
  } catch (error) {
    setSettingsStatus(`Ошибка сохранения: ${error.message}`, true);
  }
}

function scheduleSettingsSave() {
  if (isHydratingSettings) return;
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(() => saveSettings(), 700);
}

function syncCredentialGateToSettings() {
  settingsForm.rutracker_username.value = gateUsername.value;
  if (gatePassword.value) {
    settingsForm.rutracker_password.value = gatePassword.value;
  }
}

settingsToggle.addEventListener("click", () => {
  settingsDrawer.hidden = !settingsDrawer.hidden;
});

themeToggle.addEventListener("click", () => {
  applyTheme(document.body.classList.contains("light") ? "dark" : "light");
});

backgroundToggle.addEventListener("change", () => {
  saveSettings({ background_enabled: backgroundToggle.checked });
});

startupInstallButton?.addEventListener("click", () => {
  installStartup();
});

for (const eventName of ["input", "change"]) {
  gateUsername.addEventListener(eventName, () => {
    syncCredentialGateToSettings();
    scheduleSettingsSave();
  });
  gatePassword.addEventListener(eventName, () => {
    syncCredentialGateToSettings();
    scheduleSettingsSave();
  });
}

modalCloseButton.addEventListener("click", closeMovieModal);
metadataButton.addEventListener("click", () => refreshMetadata());

movieModal.addEventListener("click", (event) => {
  if (event.target === movieModal) closeMovieModal();
});

confirmModal.addEventListener("click", (event) => {
  if (event.target === confirmModal) closeConfirmModal(false);
});

duplicateModal.addEventListener("click", (event) => {
  if (event.target === duplicateModal) closeDuplicateModal("keep");
});

confirmCancelButton.addEventListener("click", () => closeConfirmModal(false));
confirmOkButton.addEventListener("click", () => closeConfirmModal(true));
duplicateKeepBothButton.addEventListener("click", () => closeDuplicateModal("keep"));
duplicateDeleteOldButton.addEventListener("click", () => closeDuplicateModal("delete-old"));
duplicateDeleteNewButton.addEventListener("click", () => closeDuplicateModal("delete-new"));

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !duplicateModal.hidden) {
    closeDuplicateModal("keep");
    return;
  }
  if (event.key === "Escape" && !confirmModal.hidden) {
    closeConfirmModal(false);
    return;
  }
  if (event.key === "Escape" && !movieModal.hidden) closeMovieModal();
});

movieForm.addEventListener("submit", saveMovie);

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearTimeout(settingsSaveTimer);
  await saveSettings();
});

settingsForm.addEventListener("input", (event) => {
  if (event.target.matches("input[type='checkbox']")) return;
  scheduleSettingsSave();
});

settingsForm.addEventListener("change", (event) => {
  if (isHydratingSettings) return;
  if (event.target.matches("input[type='checkbox']")) {
    saveSettings();
  }
});

checkAllButton.addEventListener("click", async () => {
  checkAllRunning = true;
  renderCheckAllButton();
  statusLine.textContent = "Запускаем проверку всех карточек...";
  try {
    const payload = await api("/api/check-all", { method: "POST" });
    syncCheckPayload(payload);
    renderCheckAllButton();
    renderCards();
    startCheckPolling();
    if (payload.check_all_started) {
      statusLine.textContent = "Проверка запущена: карточки будут гаснуть по одной после ответа RuTracker.";
    } else if (checkAllRunning) {
      statusLine.textContent = "Проверка уже идет.";
    } else if (lastCheckAllSummary) {
      statusLine.textContent = formatCheckAllSummary(lastCheckAllSummary);
    } else {
      statusLine.textContent = "Проверка не запущена.";
    }
  } catch (error) {
    checkAllRunning = false;
    renderCheckAllButton();
    statusLine.textContent = `Проверка не удалась: ${error.message}`;
  }
});

updateButton.addEventListener("click", applyUpdate);

async function heartbeat() {
  try {
    await api("/api/heartbeat", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (error) {
    // Если сервер уже закрывается, следующий запуск приложения поднимет его снова.
  }
}

applyTheme(localStorage.getItem("theme") || "dark");
hydrateIcons();
heartbeat();
setInterval(heartbeat, 10000);
setInterval(refreshRuntime, 15000);
setInterval(() => refreshUpdateStatus(false), UPDATE_POLL_INTERVAL_MS);

load().catch((error) => {
  statusLine.textContent = error.message;
});
