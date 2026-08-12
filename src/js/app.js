/* API Hub — Renderer (NVIDIA + OpenCode Zen) */

const api = window.nvidiaHub;

const PROVIDER_META = {
  nvidia: {
    id: "nvidia",
    label: "NVIDIA NIM",
    short: "NVIDIA",
    placeholder: "nvapi-…",
    keyLabel: "NVIDIA API key",
    defaultBaseUrl: "https://integrate.api.nvidia.com",
  },
  opencode: {
    id: "opencode",
    label: "OpenCode Zen",
    short: "OpenCode",
    placeholder: "sk-…",
    keyLabel: "OpenCode Zen API key",
    defaultBaseUrl: "https://opencode.ai/zen",
  },
  kilo: {
    id: "kilo",
    label: "Kilo Code",
    short: "Kilo",
    placeholder: "Free tier — no key needed",
    keyLabel: "Kilo token (optional)",
    defaultBaseUrl: "https://api.kilo.ai/api/gateway",
    keyless: true,
  },
};

const state = {
  theme: "dark",
  status: null,
  config: null,
  activeProvider: "nvidia",
  keysByProvider: Object.fromEntries(
    Object.keys(PROVIDER_META).map((pid) => [pid, []])
  ),
  keysDirtyByProvider: Object.fromEntries(
    Object.keys(PROVIDER_META).map((pid) => [pid, false])
  ),
  revealKeys: false,
  keyFilter: "",
  logs: [],
  modalMode: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function toast(message, type = "info") {
  const stack = $("#toastStack");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-dot"></span><span>${escapeHtml(message)}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    el.style.transition = "all 200ms ease";
    setTimeout(() => el.remove(), 220);
  }, 2800);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "--:--:--";
  }
}

function maskKey(key) {
  if (!key || key.length < 12) return "••••••••";
  return `${key.slice(0, 8)}…${key.slice(-6)}`;
}

// ---------- Dynamic provider UI (driven by PROVIDER_META) ----------
function renderProviderTabs() {
  const root = $("#providerTabs");
  if (!root) return;
  root.innerHTML = Object.values(PROVIDER_META)
    .map(
      (m) =>
        `<button type="button" class="provider-tab${m.id === state.activeProvider ? " active" : ""}" data-provider="${m.id}">${escapeHtml(m.label)}</button>`
    )
    .join("");
  initProviderTabs();
}

function renderDefaultProviderSelect() {
  const sel = $("#cfgDefaultProvider");
  if (!sel) return;
  sel.innerHTML = Object.values(PROVIDER_META)
    .map((m) => `<option value="${m.id}">${escapeHtml(m.label)}</option>`)
    .join("");
}

function renderBaseUrlFields() {
  const root = $("#baseUrlFields");
  if (!root) return;
  root.innerHTML = Object.values(PROVIDER_META)
    .map(
      (m) => `
        <label class="field">
          <span class="field-label">${escapeHtml(m.label)} base URL</span>
          <input type="url" id="cfgBase_${m.id}" spellcheck="false" />
          <span class="field-hint">Default: ${escapeHtml(m.defaultBaseUrl)}</span>
        </label>`
    )
    .join("");
}

function baseUrlField(pid) {
  const el = document.getElementById(`cfgBase_${pid}`);
  const v = el ? el.value.trim() : "";
  return v || PROVIDER_META[pid]?.defaultBaseUrl || "";
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    return true;
  }
}

function activeKeys() {
  return state.keysByProvider[state.activeProvider] || [];
}

function setActiveKeys(keys) {
  state.keysByProvider[state.activeProvider] = keys;
}

function totalKeyCount() {
  return Object.values(state.keysByProvider).reduce((n, arr) => n + (arr?.length || 0), 0);
}

// ---------- Theme ----------
const THEMES = ["dark", "premium", "ocean", "crimson", "violet", "arctic", "ember", "mint", "sapphire", "rose", "carbon", "aurora"];
const THEME_BG = {
  dark: "#07090d",
  premium: "#0c0a14",
  ocean: "#061018",
  crimson: "#12080b",
  violet: "#0e0a1a",
  arctic: "#0a0e14",
  ember: "#140c06",
  mint: "#06140f",
  sapphire: "#0a0d18",
  rose: "#110d16",
  carbon: "#0e1013",
  aurora: "#081214",
};

async function initTheme() {
  try {
    const settings = await api.getSettings();
    const t = THEMES.includes(settings.theme) ? settings.theme : "dark";
    applyTheme(t);
  } catch {
    applyTheme("dark");
  }

  $$(".theme-card").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const theme = btn.dataset.theme;
      if (!THEMES.includes(theme)) return;
      applyTheme(theme);
      try {
        await api.setTheme(theme);
      } catch (_) {}
    });
  });
}

function applyTheme(theme) {
  const t = THEMES.includes(theme) ? theme : "dark";
  state.theme = t;
  document.documentElement.setAttribute("data-theme", t);
  document.body.style.background = THEME_BG[t] || THEME_BG.dark;
  $$(".theme-card").forEach((b) => b.classList.toggle("active", b.dataset.theme === t));
}

// ---------- Navigation ----------
function initNav() {
  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      $$(".nav-item").forEach((b) => b.classList.toggle("active", b === btn));
      $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
    });
  });
}

// ---------- Window controls ----------
function initWindowControls() {
  $("#btnMin").addEventListener("click", () => api.minimize());
  $("#btnMax").addEventListener("click", async () => {
    await api.maximize();
  });
  $("#btnClose").addEventListener("click", () => api.close());
}

// ---------- Hub controls ----------
function initHubControls() {
  $("#btnToggleHub").addEventListener("click", async () => {
    const running = state.status?.running || state.status?.processAlive;
    try {
      if (running) {
        await api.stopHub();
        toast("Hub stopped", "info");
      } else {
        await api.startHub();
        toast("Hub starting…", "success");
      }
      await refreshStatus();
    } catch (err) {
      toast(err.message || "Hub action failed", "error");
    }
  });

  $("#btnRestart").addEventListener("click", async () => {
    try {
      await api.restartHub();
      toast("Hub restarted", "success");
      await refreshStatus();
    } catch (err) {
      toast(err.message || "Restart failed", "error");
    }
  });

  $("#btnCopyEndpoint").addEventListener("click", async () => {
    const url = state.status?.endpoint || $("#endpointUrl").textContent;
    await copyText(url);
    toast("Default endpoint copied", "success");
  });
}

// ---------- Status UI ----------
async function refreshStatus() {
  try {
    const status = await api.getStatus();
    renderStatus(status);
  } catch (err) {
    console.error(err);
  }
}

function renderStatus(status) {
  state.status = status;
  const online = Boolean(status?.healthy || status?.running);
  const processAlive = Boolean(status?.processAlive);
  const healthy = Boolean(status?.healthy);

  // Live pill removed from title bar — status shown on dashboard only

  $("#statStatus").textContent = healthy ? "Online" : processAlive ? "Starting" : "Offline";
  const chip = $("#chipHealth");
  if (healthy) {
    chip.textContent = "Healthy";
    chip.className = "stat-chip ok";
  } else if (processAlive) {
    chip.textContent = "Booting";
    chip.className = "stat-chip";
  } else {
    chip.textContent = "Down";
    chip.className = "stat-chip bad";
  }

  // Total keys across providers
  let totalKeys = totalKeyCount();
  if (status?.config?.providers) {
    totalKeys = Object.values(status.config.providers).reduce(
      (n, p) => n + (p.keys_count || 0),
      0
    );
  } else if (status?.health?.providers) {
    totalKeys = Object.values(status.health.providers).reduce(
      (n, p) => n + (p.keys_loaded || 0),
      0
    );
  }

  $("#statKeys").textContent = String(totalKeys);
  $("#navKeyCount").textContent = String(totalKeys);
  $("#statPort").textContent = status?.config?.port ?? "—";

  const def = status?.config?.default_provider || "nvidia";
  const defMeta = PROVIDER_META[def];
  $("#statDefaultProvider").textContent = defMeta?.short || def;
  $("#defaultProviderTag").textContent = def;

  if (status?.endpoint) {
    $("#endpointUrl").textContent = status.endpoint;
  }

  const curlProv = status?.config?.default_provider || "nvidia";
  const curlEndpoint =
    status?.endpoints?.[curlProv] ||
    status?.config?.providers?.[curlProv]?.endpoint ||
    `http://127.0.0.1:59714/${curlProv}/v1`;
  $("#sampleCurl").textContent = `curl ${curlEndpoint}/models -H "Authorization: Bearer any-key"`;

  if (status?.config) {
    $("#metaTimeout").textContent = `${status.config.timeout}s`;
    $("#metaProxy").textContent = status.config.proxy_enabled
      ? `${String(status.config.proxy_type).toUpperCase()} ${status.config.proxy_host}:${status.config.proxy_port}`
      : "Disabled";

    const anon =
      Boolean(status.config.anonymous_enabled) ||
      Boolean(status.health?.anonymous_enabled);
    const metaAnon = $("#metaAnonymous");
    if (metaAnon) {
      const tls = status.health?.anonymous_tls;
      metaAnon.textContent = anon
        ? tls === "curl_cffi"
          ? "On · TLS rotate"
          : tls
            ? "On · headers only"
            : "On"
        : "Off";
      metaAnon.classList.toggle("anon-on", anon);
      metaAnon.classList.toggle("anon-off", !anon);
    }

    if (status.config.providers) {
      const parts = Object.entries(status.config.providers).map(
        ([id, p]) => `${PROVIDER_META[id]?.short || id}: ${p.keys_count || 0}`
      );
      $("#metaPools").textContent = parts.join(" · ");
    }
  }

  renderProviderCards(status);

  const powerState = $("#powerState");
  const toggleBtn = $("#btnToggleHub");
  const toggleLabel = $("#toggleLabel");
  const activityPulse = $("#activityPulse");

  if (processAlive || healthy) {
    powerState.textContent = healthy ? "Running" : "Starting…";
    powerState.classList.add("running");
    toggleBtn.classList.add("running");
    toggleLabel.textContent = "Stop";
    activityPulse.classList.add("live");
  } else {
    powerState.textContent = "Stopped";
    powerState.classList.remove("running");
    toggleBtn.classList.remove("running");
    toggleLabel.textContent = "Start";
    activityPulse.classList.remove("live");
  }
}

function renderProviderCards(status) {
  const root = $("#providerCards");
  if (!root) return;

  const defaultProvider = status?.config?.default_provider || "nvidia";
  const providers = status?.config?.providers || {};
  const healthProviders = status?.health?.providers || {};
  const endpoints = status?.endpoints || {};

  const ids = Object.keys(PROVIDER_META);
  root.innerHTML = ids
    .map((pid) => {
      const meta = PROVIDER_META[pid];
      const p = providers[pid] || {};
      const h = healthProviders[pid] || {};
      const label = p.label || meta.label;
      const base = p.base_url || h.base_url || "—";
      const keys =
        p.keys_count ?? h.keys_loaded ?? state.keysByProvider[pid]?.length ?? 0;
      const keyless = Boolean(meta.keyless);
      const next =
        h.next_key_index !== undefined ? h.next_key_index : "—";
      const endpoint =
        p.endpoint || endpoints[pid] || `http://127.0.0.1:59714/${pid}/v1`;
      const isDefault = pid === defaultProvider;

      return `
        <div class="provider-card ${isDefault ? "is-default" : ""}" data-provider="${pid}">
          <div class="provider-card-top">
            <div>
              <div class="provider-card-title">${escapeHtml(label)}</div>
              <div class="provider-card-sub">${escapeHtml(base)}/v1</div>
            </div>
            ${isDefault ? '<span class="provider-badge">Default</span>' : ""}
          </div>
          <div class="provider-card-stats">
            <div class="provider-stat">
              <span class="provider-stat-val">${keyless && !keys ? "Free" : keys}</span>
              <span class="provider-stat-label">${keyless && !keys ? "No key needed" : "Keys in pool"}</span>
            </div>
            <div class="provider-stat">
              <span class="provider-stat-val">${next}</span>
              <span class="provider-stat-label">Next index</span>
            </div>
          </div>
          <div class="provider-endpoint-row">
            <code title="${escapeHtml(endpoint)}">${escapeHtml(endpoint)}</code>
            <button type="button" class="icon-btn" data-copy-endpoint="${escapeHtml(endpoint)}" title="Copy endpoint">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            </button>
          </div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll("[data-copy-endpoint]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await copyText(btn.dataset.copyEndpoint);
      toast("Endpoint copied", "success");
    });
  });
}

// ---------- Config / Forms ----------
async function loadConfig() {
  const config = await api.getConfig();
  state.config = config;

  for (const pid of Object.keys(PROVIDER_META)) {
    const p = config.providers?.[pid];
    state.keysByProvider[pid] = (p?.keys || []).map((k) => ({
      id: k.id,
      full: k.full,
      preview: k.preview,
    }));
    state.keysDirtyByProvider[pid] = false;
  }

  $("#cfgHost").value = config.host || "127.0.0.1";
  $("#cfgPort").value = config.port ?? 59714;
  $("#cfgTimeout").value = config.timeout ?? 300;
  $("#cfgDefaultProvider").value = config.default_provider || "nvidia";
  for (const pid of Object.keys(PROVIDER_META)) {
    const el = document.getElementById(`cfgBase_${pid}`);
    if (el) el.value = config.providers?.[pid]?.base_url || "";
  }

  const anonEl = $("#cfgAnonymousEnabled");
  if (anonEl) anonEl.checked = Boolean(config.anonymous_enabled);
  $("#cfgProxyEnabled").checked = Boolean(config.proxy_enabled);
  $("#cfgProxyType").value = config.proxy_type || "socks5";
  $("#cfgProxyHost").value = config.proxy_host || "127.0.0.1";
  $("#cfgProxyPort").value = config.proxy_port ?? 1080;
  const ghAnon = $("#cfgGithubProxyEnabled");
  if (ghAnon) ghAnon.checked = Boolean(config.github_proxy_enabled);
  const ghRepoEl = $("#cfgGithubRepo");
  if (ghRepoEl) ghRepoEl.value = config.github_repo || "Amiro3D/api-hub";
  refreshGithubProxyStatus();
  updateProxyFieldsState();
  updateAnonymousUi();

  setProviderTab(state.activeProvider);
  renderKeys();
  updateKeysSaveButton();
}

function updateProxyFieldsState() {
  const enabled = $("#cfgProxyEnabled").checked;
  $("#proxyFields").classList.toggle("disabled", !enabled);
}

function updateAnonymousUi() {
  const el = $("#cfgAnonymousEnabled");
  const panel = document.querySelector(".privacy-panel");
  if (panel && el) panel.classList.toggle("anon-active", el.checked);
}

function initForms() {
  $("#cfgProxyEnabled").addEventListener("change", updateProxyFieldsState);
  const anonEl = $("#cfgAnonymousEnabled");
  if (anonEl) {
    anonEl.addEventListener("change", updateAnonymousUi);
    updateAnonymousUi();
  }

  $("#btnSaveSettings").addEventListener("click", async () => {
    try {
      await savePartialConfig({
        host: $("#cfgHost").value.trim(),
        port: Number($("#cfgPort").value),
        timeout: Number($("#cfgTimeout").value),
        default_provider: $("#cfgDefaultProvider").value,
        anonymous_enabled: $("#cfgAnonymousEnabled").checked,
        providers: Object.fromEntries(
          Object.keys(PROVIDER_META).map((pid) => [
            pid,
            {
              base_url: baseUrlField(pid),
              keys: (state.keysByProvider[pid] || []).map((k) => k.full),
            },
          ])
        ),
      });
      toast(
        $("#cfgAnonymousEnabled").checked
          ? "Settings saved — anonymous mode ON (rotates every request)"
          : "Settings saved",
        "success"
      );
    } catch (err) {
      toast(err.message || "Save failed", "error");
    }
  });

  $("#btnSaveProxy").addEventListener("click", async () => {
    try {
      await savePartialConfig({
        proxy_enabled: $("#cfgProxyEnabled").checked,
        proxy_type: $("#cfgProxyType").value,
        proxy_host: $("#cfgProxyHost").value.trim(),
        proxy_port: Number($("#cfgProxyPort").value),
        github_proxy_enabled: $("#cfgGithubProxyEnabled")?.checked,
        github_repo: $("#cfgGithubRepo")?.value.trim(),
      });
      toast("Proxy settings saved", "success");
      refreshGithubProxyStatus();
    } catch (err) {
      toast(err.message || "Save failed", "error");
    }
  });

  const startGhBtn = $("#btnStartGhProxy");
  if (startGhBtn) {
    startGhBtn.addEventListener("click", async () => {
      try {
        toast("Triggering GitHub Action runner…", "info");
        const port = state.config?.port || 59714;
        const host = state.config?.host || "127.0.0.1";
        const res = await fetch(`http://${host}:${port}/github-proxy/start`, { method: "POST" });
        const data = await res.json();
        if (res.ok) {
          toast("Runner starting! Cloudflare Tunnel initializing…", "success");
          refreshGithubProxyStatus();
        } else {
          toast(data.message || "Failed to start runner", "error");
        }
      } catch (err) {
        toast(err.message || "Failed to start runner", "error");
      }
    });
  }

  const stopGhBtn = $("#btnStopGhProxy");
  if (stopGhBtn) {
    stopGhBtn.addEventListener("click", async () => {
      try {
        const port = state.config?.port || 59714;
        const host = state.config?.host || "127.0.0.1";
        const res = await fetch(`http://${host}:${port}/github-proxy/stop`, { method: "POST" });
        const data = await res.json();
        if (res.ok) {
          toast("Runner stopped", "info");
          refreshGithubProxyStatus();
        } else {
          toast(data.message || "Failed to stop runner", "error");
        }
      } catch (err) {
        toast(err.message || "Failed to stop runner", "error");
      }
    });
  }

  $("#btnOpenConfig").addEventListener("click", () => api.openConfigFolder());
}

async function refreshGithubProxyStatus() {
  try {
    const port = state.config?.port || 59714;
    const host = state.config?.host || "127.0.0.1";
    const res = await fetch(`http://${host}:${port}/github-proxy/status`);
    if (!res.ok) return;
    const data = await res.json();

    const badge = $("#ghProxyStatusBadge");
    const urlCode = $("#ghProxyTunnelUrl");

    const status = data.status || "stopped";
    if (badge) {
      badge.textContent = status.toUpperCase();
      badge.className = `u-badge ${status}`;
    }

    if (urlCode) {
      if (status === "running" && data.tunnel_url) {
        urlCode.textContent = data.tunnel_url;
      } else if (status === "starting") {
        urlCode.textContent = "Connecting to Cloudflare Tunnel…";
      } else {
        urlCode.textContent = "None (Runner Stopped)";
      }
    }
  } catch (err) {
    // Ignore offline backend errors
  }
}

async function savePartialConfig(partial = {}) {
  const providers = Object.fromEntries(
    Object.keys(PROVIDER_META).map((pid) => [
      pid,
      {
        label: PROVIDER_META[pid].label,
        base_url: baseUrlField(pid),
        keys: (state.keysByProvider[pid] || []).map((k) => k.full),
      },
    ])
  );

  // Merge per-provider patches without dropping the other pool
  if (partial.providers) {
    for (const [pid, pdata] of Object.entries(partial.providers)) {
      if (!pdata) continue;
      providers[pid] = {
        ...providers[pid],
        ...pdata,
        keys: pdata.keys !== undefined ? pdata.keys : providers[pid].keys,
      };
    }
  }

  if (partial.provider_id && partial.keys !== undefined) {
    const pid = partial.provider_id;
    providers[pid] = {
      ...providers[pid],
      keys: partial.keys,
    };
  }

  const payload = {
    host: partial.host ?? $("#cfgHost").value.trim(),
    port: Number(partial.port ?? $("#cfgPort").value),
    timeout: Number(partial.timeout ?? $("#cfgTimeout").value),
    default_provider: partial.default_provider ?? $("#cfgDefaultProvider").value,
    anonymous_enabled:
      partial.anonymous_enabled !== undefined
        ? partial.anonymous_enabled
        : $("#cfgAnonymousEnabled").checked,
    proxy_enabled:
      partial.proxy_enabled !== undefined
        ? partial.proxy_enabled
        : $("#cfgProxyEnabled").checked,
    proxy_type: partial.proxy_type ?? $("#cfgProxyType").value,
    proxy_host: partial.proxy_host ?? $("#cfgProxyHost").value.trim(),
    proxy_port: Number(partial.proxy_port ?? $("#cfgProxyPort").value),
    github_proxy_enabled:
      partial.github_proxy_enabled !== undefined
        ? partial.github_proxy_enabled
        : $("#cfgGithubProxyEnabled")?.checked ?? false,
    github_repo: partial.github_repo ?? $("#cfgGithubRepo")?.value.trim() ?? "Amiro3D/api-hub",
    providers,
  };

  if (partial.provider_id && partial.keys !== undefined) {
    payload.provider_id = partial.provider_id;
    payload.keys = partial.keys;
  }

  const saved = await api.saveConfig(payload);
  state.config = saved;

  for (const pid of Object.keys(PROVIDER_META)) {
    const p = saved.providers?.[pid];
    state.keysByProvider[pid] = (p?.keys || []).map((k) => ({
      id: k.id,
      full: k.full,
      preview: k.preview,
    }));
    state.keysDirtyByProvider[pid] = false;
  }

  renderKeys();
  updateKeysSaveButton();
  await refreshStatus();
  return saved;
}

// ---------- Provider tabs + Keys ----------
function setProviderTab(pid) {
  state.activeProvider = pid;
  $$(".provider-tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.provider === pid)
  );
  renderKeys();
  updateKeysSaveButton();
}

function initProviderTabs() {
  $$(".provider-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      setProviderTab(tab.dataset.provider);
    });
  });
}

function renderKeys() {
  const list = $("#keysList");
  const keys = activeKeys();
  const filter = state.keyFilter.toLowerCase();
  const meta = PROVIDER_META[state.activeProvider];
  const filtered = keys.filter((k) => {
    if (!filter) return true;
    return (
      k.full.toLowerCase().includes(filter) ||
      k.preview.toLowerCase().includes(filter)
    );
  });

  $("#keysSummary").textContent = `${keys.length} key${keys.length === 1 ? "" : "s"} in ${meta.label} pool`;
  $("#navKeyCount").textContent = String(totalKeyCount());

  if (!filtered.length) {
    list.innerHTML = `<div class="keys-empty">${
      keys.length
        ? "No keys match your filter"
        : meta.keyless
          ? "Free tier — no key required. Just save and connect."
          : `No API keys yet — add your first ${meta.short} key`
    }</div>`;
    return;
  }

  list.innerHTML = filtered
    .map((k) => {
      const display = state.revealKeys ? k.full : k.preview;
      const realIndex = keys.indexOf(k);
      return `
        <div class="key-row" data-index="${realIndex}">
          <div class="key-index">${String(realIndex + 1).padStart(2, "0")}</div>
          <div class="key-preview" title="${escapeHtml(k.preview)}">${escapeHtml(display)}</div>
          <div class="key-actions">
            <button type="button" class="icon-btn" data-copy="${realIndex}" title="Copy">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            </button>
            <button type="button" class="icon-btn" data-remove="${realIndex}" title="Remove">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
            </button>
          </div>
        </div>
      `;
    })
    .join("");

  list.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const idx = Number(btn.dataset.copy);
      await copyText(activeKeys()[idx].full);
      toast("Key copied", "success");
    });
  });

  list.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.remove);
      const next = [...activeKeys()];
      next.splice(idx, 1);
      setActiveKeys(next);
      state.keysDirtyByProvider[state.activeProvider] = true;
      renderKeys();
      updateKeysSaveButton();
    });
  });
}

function updateKeysSaveButton() {
  $("#btnSaveKeys").disabled = !state.keysDirtyByProvider[state.activeProvider];
}

function initKeys() {
  $("#keySearch").addEventListener("input", (e) => {
    state.keyFilter = e.target.value;
    renderKeys();
  });

  $("#btnRevealKeys").addEventListener("click", () => {
    state.revealKeys = !state.revealKeys;
    $("#revealLabel").textContent = state.revealKeys ? "Hide" : "Reveal";
    renderKeys();
  });

  $("#btnAddKey").addEventListener("click", () => openModal("add"));
  $("#btnImportKeys").addEventListener("click", () => openModal("bulk"));

  $("#btnSaveKeys").addEventListener("click", async () => {
    const pid = state.activeProvider;
    const meta = PROVIDER_META[pid];
    const keys = (state.keysByProvider[pid] || []).map((k) => k.full);
    if (!keys.length && !meta.keyless) {
      toast(`Add at least one key for ${meta.label}`, "error");
      return;
    }
    try {
      await savePartialConfig({
        provider_id: pid,
        keys,
        providers: {
          [pid]: {
            keys,
            base_url: baseUrlField(pid),
          },
        },
      });
      toast(`${meta.label} keys saved`, "success");
    } catch (err) {
      toast(err.message || "Save failed", "error");
    }
  });
}

// ---------- Modal ----------
function openModal(mode) {
  state.modalMode = mode;
  const root = $("#modalRoot");
  root.hidden = false;
  const meta = PROVIDER_META[state.activeProvider];

  if (mode === "add") {
    $("#modalTitle").textContent = `Add ${meta.short} Key`;
    $("#modalFieldLabel").textContent = meta.keyLabel;
    $("#modalInput").value = "";
    $("#modalInput").placeholder = meta.placeholder;
    $("#modalConfirm").textContent = "Add";
  } else {
    $("#modalTitle").textContent = `Bulk Import — ${meta.short}`;
    $("#modalFieldLabel").textContent = "Paste keys (one per line)";
    $("#modalInput").value = "";
    $("#modalInput").placeholder = `${meta.placeholder}\n${meta.placeholder}`;
    $("#modalConfirm").textContent = "Import";
  }

  setTimeout(() => $("#modalInput").focus(), 50);
}

function closeModal() {
  $("#modalRoot").hidden = true;
  state.modalMode = null;
}

function initModal() {
  $$("[data-close-modal]").forEach((el) => el.addEventListener("click", closeModal));

  $("#modalConfirm").addEventListener("click", () => {
    const raw = $("#modalInput").value.trim();
    if (!raw) {
      toast("Enter at least one key", "error");
      return;
    }

    const keys = [...activeKeys()];

    if (state.modalMode === "add") {
      const key = raw.split(/\s+/)[0];
      if (keys.some((k) => k.full === key)) {
        toast("Key already exists in this pool", "error");
        return;
      }
      keys.push({ id: keys.length, full: key, preview: maskKey(key) });
      toast("Key added — save to persist", "success");
    } else {
      const lines = raw
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean);
      let added = 0;
      for (const key of lines) {
        if (keys.some((k) => k.full === key)) continue;
        keys.push({ id: keys.length, full: key, preview: maskKey(key) });
        added++;
      }
      toast(`Imported ${added} key${added === 1 ? "" : "s"} — save to persist`, "success");
    }

    setActiveKeys(keys);
    state.keysDirtyByProvider[state.activeProvider] = true;
    renderKeys();
    updateKeysSaveButton();
    closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#modalRoot").hidden) closeModal();
  });
}

// ---------- Usage ----------
function formatCompact(n) {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1_000_000_000) {
    const x = abs / 1_000_000_000;
    return sign + (x >= 10 ? x.toFixed(0) : x.toFixed(1).replace(/\.0$/, "")) + "B";
  }
  if (abs >= 1_000_000) {
    const x = abs / 1_000_000;
    return sign + (x >= 10 ? x.toFixed(0) : x.toFixed(1).replace(/\.0$/, "")) + "M";
  }
  if (abs >= 1_000) {
    const x = abs / 1_000;
    return sign + (x >= 10 ? x.toFixed(0) : x.toFixed(1).replace(/\.0$/, "")) + "K";
  }
  return sign + String(Math.round(abs));
}

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(v >= 10240 ? 0 : 1)} KB`;
  if (v < 1024 * 1024 * 1024) return `${(v / (1024 * 1024)).toFixed(v >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  return `${(v / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatSince(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function topEntries(map, limit = 3) {
  if (!map || typeof map !== "object") return [];
  return Object.entries(map)
    .map(([k, v]) => [k, typeof v === "object" ? Number(v.requests || 0) : Number(v || 0)])
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
}

function successRate(bucket) {
  const req = Number(bucket?.requests) || 0;
  if (!req) return 0;
  return Math.round((100 * (Number(bucket.success) || 0)) / req);
}

function renderUsageStats(el, bucket) {
  if (!el) return;
  if (!bucket) {
    el.innerHTML = `
      <div class="u-kpi"><span class="u-kpi-val">—</span><span class="u-kpi-label">Tokens</span></div>
      <div class="u-kpi"><span class="u-kpi-val">—</span><span class="u-kpi-label">Requests</span></div>
      <div class="u-kpi"><span class="u-kpi-val">—</span><span class="u-kpi-label">Success</span></div>
      <div class="u-kpi"><span class="u-kpi-val">—</span><span class="u-kpi-label">Latency</span></div>`;
    return;
  }
  const rate = successRate(bucket);
  const items = [
    { label: "Tokens", val: formatCompact(bucket.total_tokens), cls: "accent" },
    { label: "Requests", val: formatCompact(bucket.requests), cls: "" },
    { label: "Success", val: `${rate}%`, cls: rate >= 90 ? "ok" : rate >= 70 ? "" : "bad" },
    {
      label: "Latency",
      val: bucket.avg_latency_ms ? `${formatCompact(bucket.avg_latency_ms)}ms` : "—",
      cls: "",
    },
  ];
  el.innerHTML = items
    .map(
      (it) => `
      <div class="u-kpi">
        <span class="u-kpi-val ${it.cls}">${escapeHtml(String(it.val))}</span>
        <span class="u-kpi-label">${escapeHtml(it.label)}</span>
      </div>`
    )
    .join("");
}

function renderUsageBreakdown(el, bucket) {
  if (!el) return;
  if (!bucket) {
    el.innerHTML = "";
    return;
  }

  const rows = [
    ["Prompt", Number(bucket.prompt_tokens) || 0],
    ["Completion", Number(bucket.completion_tokens) || 0],
    ["Errors", Number(bucket.errors) || 0],
  ];

  // Prefer top model as a compact insight row when available
  const topModel = topEntries(bucket.by_model, 1)[0];
  if (topModel) rows.push([String(topModel[0]).slice(0, 14), topModel[1]]);

  const max = Math.max(...rows.map((r) => r[1]), 1);
  el.innerHTML = rows
    .map(([label, val]) => {
      const pct = Math.max(3, Math.round((100 * val) / max));
      return `
        <div class="u-bar-row">
          <span class="u-bar-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
          <div class="u-bar-track"><i style="width:${pct}%"></i></div>
          <span class="u-bar-val">${formatCompact(val)}</span>
        </div>`;
    })
    .join("");

  requestAnimationFrame(() => {
    el.querySelectorAll(".u-bar-track > i").forEach((bar) => {
      const w = bar.style.width;
      bar.style.width = "0";
      requestAnimationFrame(() => {
        bar.style.width = w;
      });
    });
  });
}

function renderUsageRecent(recent) {
  const body = $("#usageRecentBody");
  const countEl = $("#usageRecentCount");
  if (countEl) countEl.textContent = String(recent?.length || 0);
  if (!body) return;

  if (!recent || !recent.length) {
    body.innerHTML = `<tr><td colspan="7" class="u-empty">No requests yet</td></tr>`;
    return;
  }

  body.innerHTML = recent
    .slice(0, 40)
    .map((r) => {
      const statusClass = r.ok ? "ok" : "bad";
      const modeClass = r.stream ? "stream" : "";
      const tokens = Number(r.total_tokens) || 0;
      return `<tr>
        <td>${escapeHtml(formatTime(r.ts))}</td>
        <td>${escapeHtml(r.provider || "—")}</td>
        <td title="${escapeHtml(r.model || "")}">${escapeHtml((r.model || "—").slice(0, 22))}</td>
        <td><span class="u-chip ${statusClass}">${escapeHtml(String(r.status ?? "—"))}</span></td>
        <td>${formatCompact(tokens)}</td>
        <td>${r.latency_ms != null ? formatCompact(r.latency_ms) + "ms" : "—"}</td>
        <td><span class="u-chip ${modeClass}">${r.stream ? "stream" : "json"}</span></td>
      </tr>`;
    })
    .join("");
}

async function refreshUsage() {
  try {
    const data = await api.getUsage();
    if (!data?.ok) {
      renderUsageStats($("#sessionUsageStats"), null);
      renderUsageStats($("#allTimeUsageStats"), null);
      renderUsageBreakdown($("#sessionUsageBreakdown"), null);
      renderUsageBreakdown($("#allTimeUsageBreakdown"), null);
      if ($("#sessionUsageSince")) $("#sessionUsageSince").textContent = "Hub offline";
      if ($("#allTimeUsageSince")) $("#allTimeUsageSince").textContent = "—";
      renderUsageRecent([]);
      return;
    }

    const session = data.session;
    const allTime = data.all_time;

    if ($("#sessionUsageSince")) {
      $("#sessionUsageSince").textContent = session?.started_at
        ? formatSince(session.started_at)
        : "Current process";
    }
    if ($("#allTimeUsageSince")) {
      $("#allTimeUsageSince").textContent = allTime?.started_at
        ? formatSince(allTime.started_at)
        : "All sessions";
    }

    renderUsageStats($("#sessionUsageStats"), session);
    renderUsageStats($("#allTimeUsageStats"), allTime);
    renderUsageBreakdown($("#sessionUsageBreakdown"), session);
    renderUsageBreakdown($("#allTimeUsageBreakdown"), allTime);
    renderUsageRecent(session?.recent || []);
  } catch (err) {
    console.error(err);
  }
}

function initUsage() {
  $("#btnRefreshUsage")?.addEventListener("click", () => refreshUsage());
  $("#btnResetSessionUsage")?.addEventListener("click", async () => {
    try {
      const res = await api.resetUsage("session");
      if (!res?.ok) throw new Error(res?.error || "Reset failed");
      toast("Session usage reset", "info");
      await refreshUsage();
    } catch (err) {
      toast(err.message || "Reset failed — start the hub first", "error");
    }
  });
  $("#btnResetAllUsage")?.addEventListener("click", async () => {
    if (!confirm("Reset ALL-TIME usage counters? This cannot be undone.")) return;
    try {
      const res = await api.resetUsage("all");
      if (!res?.ok) throw new Error(res?.error || "Reset failed");
      toast("All-time usage reset", "info");
      await refreshUsage();
    } catch (err) {
      toast(err.message || "Reset failed — start the hub first", "error");
    }
  });

  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.view === "usage") refreshUsage();
    });
  });

  setInterval(() => {
    const view = $("#view-usage");
    if (view?.classList.contains("active")) refreshUsage();
  }, 4000);
}

// ---------- Logs ----------
function appendLog(entry, scroll = true) {
  state.logs.push(entry);
  if (state.logs.length > 500) state.logs = state.logs.slice(-500);

  const consoleEl = $("#logsConsole");
  const empty = consoleEl.querySelector(".logs-empty");
  if (empty) empty.remove();

  const line = document.createElement("div");
  line.className = "log-line";
  line.innerHTML = `
    <span class="log-ts">${formatTime(entry.ts)}</span>
    <span class="log-level ${entry.level}">${escapeHtml(entry.level)}</span>
    <span class="log-msg">${escapeHtml(entry.message)}</span>
  `;
  consoleEl.appendChild(line);
  if (scroll) consoleEl.scrollTop = consoleEl.scrollHeight;

  pushActivity(entry);
}

function pushActivity(entry) {
  const list = $("#activityList");
  const empty = list.querySelector(".activity-empty");
  if (empty) empty.remove();

  const item = document.createElement("div");
  item.className = "activity-item";
  item.innerHTML = `
    <span class="activity-level ${entry.level}"></span>
    <div class="activity-body">
      <div class="activity-msg">${escapeHtml(entry.message)}</div>
      <div class="activity-time">${formatTime(entry.ts)}</div>
    </div>
  `;
  list.prepend(item);

  while (list.children.length > 8) {
    list.removeChild(list.lastChild);
  }
}

function renderLogsEmpty() {
  const consoleEl = $("#logsConsole");
  if (!consoleEl.children.length) {
    consoleEl.innerHTML = `<div class="logs-empty">No logs yet — start the hub to see output</div>`;
  }
}

async function initLogs() {
  try {
    const logs = await api.getLogs();
    state.logs = logs || [];
    const consoleEl = $("#logsConsole");
    consoleEl.innerHTML = "";
    if (!state.logs.length) {
      renderLogsEmpty();
    } else {
      state.logs.forEach((l) => appendLog(l, false));
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  } catch {
    renderLogsEmpty();
  }

  $("#btnClearLogs").addEventListener("click", async () => {
    await api.clearLogs();
    state.logs = [];
    $("#logsConsole").innerHTML = "";
    $("#activityList").innerHTML = `<div class="activity-empty">Start the hub to see live events</div>`;
    renderLogsEmpty();
    toast("Logs cleared", "info");
  });

  $("#btnCopyLogs").addEventListener("click", async () => {
    const text = state.logs
      .map((l) => `[${formatTime(l.ts)}] ${l.level.toUpperCase()}  ${l.message}`)
      .join("\n");
    await copyText(text || "");
    toast("Logs copied", "success");
  });

  api.onLog((entry) => appendLog(entry, true));
}

// ---------- Boot ----------
async function boot() {
  initTheme();
  initNav();
  initWindowControls();
  initHubControls();
  initForms();
  initKeys();
  initModal();
  initUsage();
  renderProviderTabs();
  renderDefaultProviderSelect();
  renderBaseUrlFields();
  await initLogs();
  refreshUsage().catch(() => {});

  try {
    await loadConfig();
  } catch (err) {
    toast(`Failed to load config: ${err.message}`, "error");
  }

  await refreshStatus();
  api.onStatus((status) => renderStatus(status));
}

boot().catch((err) => {
  console.error(err);
  toast("App failed to initialize", "error");
});
