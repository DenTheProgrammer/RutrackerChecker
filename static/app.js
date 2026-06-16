const itemListEl = document.querySelector("#itemList");
const detailPanel = document.querySelector("#detailPanel");
const queryCount = document.querySelector("#queryCount");
const addForm = document.querySelector("#addForm");
const settingsForm = document.querySelector("#settingsForm");
const settingsState = document.querySelector("#settingsState");
const statusLine = document.querySelector("#statusLine");
const checkAllButton = document.querySelector("#checkAllButton");
const stopServerButton = document.querySelector("#stopServerButton");

let state = { items: [], config: {} };
let selectedId = null;
let lastChecks = new Map();
const sessionId = crypto.randomUUID
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function setBusy(button, busy, text) {
  if (!button) return;
  button.disabled = busy;
  if (text) button.textContent = text;
}

function applySettingsToForms() {
  const { config } = state;
  statusLine.textContent = `Auto-check every ${config.check_interval_minutes} min · Telegram ${config.telegram_enabled ? "enabled" : "not configured"}`;
  settingsState.textContent = config.has_rutracker_password
    ? "RuTracker credentials saved"
    : "Enter RuTracker credentials before checking";
  settingsForm.rutracker_username.value = config.rutracker_username || "";
  settingsForm.rutracker_password.value = "";
  settingsForm.rutracker_password.placeholder = config.has_rutracker_password
    ? "Saved · leave empty to keep"
    : "Required";
  settingsForm.telegram_bot_token.value = "";
  settingsForm.telegram_bot_token.placeholder = config.has_telegram_bot_token
    ? "Saved · leave empty to keep"
    : "Optional";
  settingsForm.telegram_chat_id.value = config.telegram_chat_id || "";
  settingsForm.default_min_seeders.value = config.default_min_seeders || 5;
  settingsForm.default_min_size_gb.value = config.default_min_size_gb || 5;
  settingsForm.default_require_1080p.checked = Boolean(config.default_require_1080p);
  settingsForm.check_interval_minutes.value = config.check_interval_minutes || 360;
  settingsForm.reminder_interval_hours.value = config.reminder_interval_hours ?? 12;
  settingsForm.max_search_pages.value = config.max_search_pages || 3;
  addForm.require_1080p.checked = Boolean(config.default_require_1080p);
}

function render() {
  applySettingsToForms();
  renderList();
  renderDetail();
}

function renderList() {
  itemListEl.innerHTML = "";
  queryCount.textContent = `${state.items.length}`;

  if (!state.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-list";
    empty.textContent = "No queries yet.";
    itemListEl.append(empty);
    return;
  }

  if (!selectedId || !state.items.some((item) => item.id === selectedId)) {
    selectedId = state.items[0].id;
  }

  for (const item of state.items) {
    const button = document.createElement("button");
    button.className = "query-row";
    button.classList.toggle("selected", item.id === selectedId);
    button.innerHTML = `
      <span class="query-enabled"></span>
      <span class="query-name"></span>
      <span class="query-badge"></span>
    `;
    button.querySelector(".query-enabled").textContent = item.enabled ? "✓" : "";
    button.querySelector(".query-name").textContent = item.query;
    const badge = button.querySelector(".query-badge");
    badge.textContent = item.new_count > 0 ? item.new_count : "";
    badge.classList.toggle("empty", item.new_count <= 0);
    button.addEventListener("click", () => {
      selectedId = item.id;
      render();
    });
    itemListEl.append(button);
  }
}

function renderDetail() {
  const item = state.items.find((candidate) => candidate.id === selectedId);
  if (!item) {
    detailPanel.innerHTML = `<div class="empty-detail">Select a query.</div>`;
    return;
  }

  const lastCheck = lastChecks.get(item.id);
  const newResults = item.results.filter((result) => result.is_new);

  detailPanel.innerHTML = `
    <div class="detail-header">
      <label class="toggle">
        <input class="enabled" type="checkbox">
        <span></span>
      </label>
      <div class="detail-title">
        <a class="search-link" target="_blank" rel="noreferrer"></a>
        <div class="detail-subtitle"></div>
      </div>
      <span class="badge"></span>
    </div>
    <div class="notice"></div>
    <div class="detail-controls">
      <label>
        <span>Search query</span>
        <input class="edit-query" type="text">
      </label>
      <label>
        <span>Min seeders</span>
        <input class="min-seeders" type="number" min="0">
      </label>
      <label>
        <span>Min GB</span>
        <input class="min-size-gb" type="number" min="0" step="0.1">
      </label>
      <label class="checkbox-field">
        <input class="require-1080p" type="checkbox">
        <span>Require 1080p+</span>
      </label>
      <button class="save">Save</button>
      <button class="check">Check</button>
      <button class="open-search">Open search</button>
      <button class="reset">Reset new</button>
      <button class="delete danger">Delete</button>
    </div>
    <div class="results"></div>
  `;

  const enabled = detailPanel.querySelector(".enabled");
  const link = detailPanel.querySelector(".search-link");
  const badge = detailPanel.querySelector(".badge");
  const notice = detailPanel.querySelector(".notice");
  const editQuery = detailPanel.querySelector(".edit-query");
  const minSeeders = detailPanel.querySelector(".min-seeders");
  const minSizeGb = detailPanel.querySelector(".min-size-gb");
  const require1080p = detailPanel.querySelector(".require-1080p");
  const results = detailPanel.querySelector(".results");
  const save = detailPanel.querySelector(".save");
  const check = detailPanel.querySelector(".check");
  const openSearch = detailPanel.querySelector(".open-search");
  const reset = detailPanel.querySelector(".reset");
  const deleteButton = detailPanel.querySelector(".delete");

  enabled.checked = Boolean(item.enabled);
  link.href = item.search_url;
  link.textContent = item.query;
  detailPanel.querySelector(".detail-subtitle").textContent = `${newResults.length} pending · ${item.min_seeders}+ seeders · ${item.min_size_gb}+ GB`;
  badge.textContent = item.new_count > 0 ? `${item.new_count} new` : "0 new";
  badge.classList.toggle("empty", item.new_count <= 0);
  notice.textContent = lastCheck ? lastCheck.message : "";
  notice.classList.toggle("error", Boolean(lastCheck?.error));
  editQuery.value = item.query;
  minSeeders.value = item.min_seeders;
  minSizeGb.value = item.min_size_gb;
  require1080p.checked = Boolean(item.require_1080p);

  enabled.addEventListener("change", async () => {
    await api(`/api/items/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...item, enabled: enabled.checked }),
    });
    await load();
  });

  save.addEventListener("click", async () => {
    setBusy(save, true, "Saving");
    try {
      await api(`/api/items/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...item,
          query: editQuery.value,
          min_seeders: Number(minSeeders.value),
          min_size_gb: Number(minSizeGb.value),
          require_1080p: require1080p.checked,
        }),
      });
      await load();
    } finally {
      setBusy(save, false, "Save");
    }
  });

  check.addEventListener("click", async () => {
    setBusy(check, true, "Checking");
    try {
      const result = await api(`/api/items/${item.id}/check`, { method: "POST" });
      rememberCheck(result);
      await load();
    } catch (error) {
      lastChecks.set(item.id, { error: true, message: `Check failed: ${error.message}` });
      render();
    } finally {
      setBusy(check, false, "Check");
    }
  });

  openSearch.addEventListener("click", () => {
    window.open(item.search_url, "_blank", "noreferrer");
  });

  reset.addEventListener("click", async () => {
    setBusy(reset, true, "Resetting");
    try {
      await api(`/api/items/${item.id}/reset-new`, { method: "POST" });
      await load();
    } finally {
      setBusy(reset, false, "Reset new");
    }
  });

  deleteButton.addEventListener("click", async () => {
    if (!confirm(`Delete "${item.query}"?`)) return;
    await api(`/api/items/${item.id}`, { method: "DELETE" });
    selectedId = null;
    await load();
  });

  if (!newResults.length) {
    results.innerHTML = `<div class="empty-results">No pending new results.</div>`;
    return;
  }

  for (const result of newResults) {
    const row = document.createElement("div");
    row.className = "result";
    row.innerHTML = `
      <a href="${result.url}" target="_blank" rel="noreferrer"></a>
      <span class="result-meta"></span>
    `;
    row.querySelector("a").textContent = result.title;
    const size = result.size_label || `${((result.size_bytes || 0) / 1024 / 1024 / 1024).toFixed(1)} GB`;
    const quality = result.resolution ? `${result.resolution} · ` : "";
    row.querySelector(".result-meta").textContent = `${quality}${size} · ${result.seeders} seeders`;
    results.append(row);
  }
}

async function load() {
  state = await api("/api/items");
  render();
}

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(addForm).entries());
  data.min_seeders = Number(data.min_seeders || state.config.default_min_seeders || 5);
  data.min_size_gb = Number(data.min_size_gb || state.config.default_min_size_gb || 5);
  data.require_1080p = addForm.require_1080p.checked;
  const item = await api("/api/items", { method: "POST", body: JSON.stringify(data) });
  selectedId = item.id;
  addForm.reset();
  addForm.min_seeders.value = state.config.default_min_seeders || 5;
  addForm.min_size_gb.value = state.config.default_min_size_gb || 5;
  addForm.require_1080p.checked = Boolean(state.config.default_require_1080p);
  await load();
});

function rememberCheck(result) {
  if (!result || !result.item) return;
  lastChecks.set(result.item.id, {
    error: Boolean(result.error),
    message: result.error
      ? `Check failed: ${result.error}`
      : `Last check: ${result.raw || 0} found, ${result.matched || 0} matched filter, ${result.new || 0} new this check, ${result.pruned_new || 0} filtered out, ${result.pending_new || 0} pending.`,
  });
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = settingsForm.querySelector("button[type='submit']");
  setBusy(submitButton, true, "Saving");
  try {
    const data = Object.fromEntries(new FormData(settingsForm).entries());
    data.default_min_seeders = Number(data.default_min_seeders || 0);
    data.default_min_size_gb = Number(data.default_min_size_gb || 0);
    data.default_require_1080p = settingsForm.default_require_1080p.checked;
    data.check_interval_minutes = Number(data.check_interval_minutes || 0);
    data.reminder_interval_hours = Number(data.reminder_interval_hours || 0);
    data.max_search_pages = Number(data.max_search_pages || 3);
    await api("/api/settings", { method: "PATCH", body: JSON.stringify(data) });
    await load();
  } finally {
    setBusy(submitButton, false, "Save settings");
  }
});

checkAllButton.addEventListener("click", async () => {
  setBusy(checkAllButton, true, "Checking...");
  try {
    const summary = await api("/api/check-all", { method: "POST" });
    for (const result of summary.results || []) {
      rememberCheck(result);
      if (result.error && result.item) {
        lastChecks.set(result.item.id, {
          error: true,
          message: `Check failed: ${result.error}`,
        });
      }
    }
    await load();
    statusLine.textContent = `Check complete: ${summary.items_checked} checked, ${summary.total_new} new this check, ${summary.total_pending_new || 0} pending.`;
  } catch (error) {
    statusLine.textContent = `Check failed: ${error.message}`;
  } finally {
    setBusy(checkAllButton, false, "Check all");
  }
});

load().catch((error) => {
  statusLine.textContent = error.message;
});

async function heartbeat() {
  try {
    await api("/api/heartbeat", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (error) {
    // If the server is shutting down, the next manual launch will start it again.
  }
}

heartbeat();
setInterval(heartbeat, 10000);

stopServerButton.addEventListener("click", async () => {
  setBusy(stopServerButton, true, "Stopping");
  try {
    await api("/api/shutdown", { method: "POST" });
    statusLine.textContent = "Server stopped. You can close this tab.";
  } catch (error) {
    statusLine.textContent = "Server stopped. You can close this tab.";
  }
});
