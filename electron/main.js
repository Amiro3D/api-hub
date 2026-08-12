const { app, BrowserWindow, ipcMain, shell, nativeTheme } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn, spawnSync, exec } = require("child_process");
const http = require("http");

const ROOT = path.join(__dirname, "..");
const SETTINGS_PATH = path.join(app.getPath("userData"), "app-settings.json");

const PACKAGED = app.isPackaged;
const RESOURCES = PACKAGED ? process.resourcesPath : ROOT;
const USER_CONFIG_PATH = path.join(app.getPath("userData"), "config.json");
const CONFIG_PATH = PACKAGED ? USER_CONFIG_PATH : path.join(ROOT, "config.json");
const HUB_SCRIPT = path.join(ROOT, "nvidia_hub.py");
const HUB_BINARY = path.join(RESOURCES, "nvidia_hub.exe");

function ensurePackagedConfig() {
  if (!PACKAGED) return;
  if (!fs.existsSync(USER_CONFIG_PATH)) {
    const bundled = path.join(RESOURCES, "config.json");
    if (fs.existsSync(bundled)) {
      fs.copyFileSync(bundled, USER_CONFIG_PATH);
    }
  }
}

const PROVIDER_DEFAULTS = {
  nvidia: {
    label: "NVIDIA NIM",
    base_url: "https://integrate.api.nvidia.com",
    keys: [],
  },
  opencode: {
    label: "OpenCode Zen",
    base_url: "https://opencode.ai/zen",
    keys: [],
  },
  kilo: {
    label: "Kilo Code",
    base_url: "https://api.kilo.ai/api/gateway",
    keys: [],
  },
};

// Free tier needs no API key (auth header is omitted upstream).
const KEYLESS_PROVIDERS = ["kilo"];

let mainWindow = null;
let hubProcess = null;
let logBuffer = [];
const MAX_LOGS = 500;

function defaultAppSettings() {
  return { theme: "dark", windowBounds: null };
}

function loadAppSettings() {
  try {
    if (fs.existsSync(SETTINGS_PATH)) {
      return { ...defaultAppSettings(), ...JSON.parse(fs.readFileSync(SETTINGS_PATH, "utf8")) };
    }
  } catch (_) {}
  return defaultAppSettings();
}

function saveAppSettings(partial) {
  const next = { ...loadAppSettings(), ...partial };
  fs.mkdirSync(path.dirname(SETTINGS_PATH), { recursive: true });
  fs.writeFileSync(SETTINGS_PATH, JSON.stringify(next, null, 2), "utf8");
  return next;
}

function normalizeBaseUrl(base) {
  let b = String(base || "").trim().replace(/\/+$/, "");
  if (b.toLowerCase().endsWith("/v1")) b = b.slice(0, -3).replace(/\/+$/, "");
  return b;
}

function normalizeConfig(raw) {
  const cfg = raw && typeof raw === "object" ? raw : {};
  const providers = {};

  if (cfg.providers && typeof cfg.providers === "object") {
    for (const [pid, pdata] of Object.entries(cfg.providers)) {
      if (!pdata || typeof pdata !== "object") continue;
      const defaults = PROVIDER_DEFAULTS[pid] || { label: pid, base_url: "", keys: [] };
      providers[pid] = {
        label: pdata.label || defaults.label || pid,
        base_url: normalizeBaseUrl(pdata.base_url || pdata.nim_base || defaults.base_url),
        keys: Array.isArray(pdata.keys) ? pdata.keys.filter(Boolean) : [],
      };
    }
  } else {
    // Legacy flat config
    providers.nvidia = {
      label: "NVIDIA NIM",
      base_url: normalizeBaseUrl(cfg.nim_base || PROVIDER_DEFAULTS.nvidia.base_url),
      keys: Array.isArray(cfg.keys) ? cfg.keys.filter(Boolean) : [],
    };
    providers.opencode = {
      ...PROVIDER_DEFAULTS.opencode,
      keys: [],
    };
  }

  for (const [pid, defaults] of Object.entries(PROVIDER_DEFAULTS)) {
    if (!providers[pid]) {
      providers[pid] = {
        label: defaults.label,
        base_url: defaults.base_url,
        keys: [],
      };
    }
  }

  let default_provider = cfg.default_provider || "nvidia";
  if (!providers[default_provider]) {
    default_provider = Object.keys(providers)[0];
  }

  return {
    default_provider,
    providers,
    host: cfg.host || "127.0.0.1",
    port: Number(cfg.port ?? 59714),
    timeout: Number(cfg.timeout ?? 300),
    proxy_enabled: Boolean(cfg.proxy_enabled),
    proxy_type: (cfg.proxy_type || "socks5").toLowerCase(),
    proxy_host: cfg.proxy_host || "127.0.0.1",
    proxy_port: Number(cfg.proxy_port ?? 1080),
    anonymous_enabled: Boolean(cfg.anonymous_enabled),
  };
}

function loadConfig() {
  const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
  return normalizeConfig(raw);
}

function saveConfig(config) {
  const normalized = normalizeConfig(config);
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(normalized, null, 4), "utf8");
  return loadConfig();
}

function maskKey(key) {
  if (!key || key.length < 12) return "••••••••";
  return `${key.slice(0, 8)}…${key.slice(-6)}`;
}

function serializeConfigForUi(config) {
  const providers = {};
  for (const [pid, p] of Object.entries(config.providers || {})) {
    providers[pid] = {
      label: p.label,
      base_url: p.base_url,
      keys: (p.keys || []).map((k, i) => ({
        id: i,
        preview: maskKey(k),
        full: k,
      })),
      keys_count: (p.keys || []).length,
    };
  }
  return {
    default_provider: config.default_provider,
    providers,
    host: config.host,
    port: config.port,
    timeout: config.timeout,
    proxy_enabled: config.proxy_enabled,
    proxy_type: config.proxy_type,
    proxy_host: config.proxy_host,
    proxy_port: config.proxy_port,
    anonymous_enabled: Boolean(config.anonymous_enabled),
  };
}

function pushLog(level, message) {
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    ts: new Date().toISOString(),
    level,
    message: String(message).trimEnd(),
  };
  logBuffer.push(entry);
  if (logBuffer.length > MAX_LOGS) logBuffer = logBuffer.slice(-MAX_LOGS);
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("hub:log", entry);
  }
  return entry;
}

function isHubRunning() {
  // hubProcess is null only after we've observed (or forced) the child's exit.
  return Boolean(hubProcess && hubProcess.exitCode === null);
}

function findPython() {
  const candidates =
    process.platform === "win32" ? ["python", "py", "python3"] : ["python3", "python"];
  return candidates[0];
}

function startHub() {
  if (isHubRunning()) {
    return { ok: true, message: "Hub is already running", running: true };
  }

  const entryToCheck = PACKAGED ? HUB_BINARY : HUB_SCRIPT;
  if (!fs.existsSync(entryToCheck)) {
    const label = PACKAGED ? "nvidia_hub.exe" : "nvidia_hub.py";
    pushLog("error", `${label} not found`);
    return { ok: false, message: `${label} not found`, running: false };
  }

  // Ensure config is in multi-provider shape on disk
  try {
    const cfg = loadConfig();
    saveConfig(cfg);
  } catch (err) {
    pushLog("error", `Config error: ${err.message}`);
    return { ok: false, message: err.message, running: false };
  }

  const config = loadConfig();

  pushLog("info", `Starting hub on ${config.host}:${config.port}…`);
  pushLog(
    "info",
    `Providers: ${Object.entries(config.providers)
      .map(([id, p]) => `${id}(${(p.keys || []).length} keys)`)
      .join(", ")}`
  );

  let command, args, spawnEnv;

  if (PACKAGED) {
    command = HUB_BINARY;
    args = [];
    spawnEnv = {
      ...process.env,
      HUB_CONFIG_PATH: CONFIG_PATH,
      HUB_DATA_DIR: app.getPath("userData"),
      PYTHONUNBUFFERED: "1",
    };
  } else {
    command = findPython();
    args = [HUB_SCRIPT];
    spawnEnv = { ...process.env, HUB_DATA_DIR: ROOT, PYTHONUNBUFFERED: "1" };
  }

  hubProcess = spawn(command, args, {
    cwd: PACKAGED ? RESOURCES : ROOT,
    env: spawnEnv,
    windowsHide: true,
  });

  hubProcess.stdout.on("data", (data) => {
    String(data)
      .split(/\r?\n/)
      .filter(Boolean)
      .forEach((line) => pushLog("info", line));
  });

  hubProcess.stderr.on("data", (data) => {
    String(data)
      .split(/\r?\n/)
      .filter(Boolean)
      .forEach((line) => {
        const level = /error|exception|traceback/i.test(line) ? "error" : "warn";
        pushLog(level, line);
      });
  });

  hubProcess.on("error", (err) => {
    pushLog("error", `Failed to start Python: ${err.message}`);
    hubProcess = null;
    broadcastStatus();
  });

  hubProcess.on("exit", (code, signal) => {
    pushLog("info", `Hub process exited (code=${code}, signal=${signal || "none"})`);
    hubProcess = null;
    broadcastStatus();
  });

  pushLog("success", "Hub process spawned");
  setTimeout(broadcastStatus, 800);
  return { ok: true, message: "Hub started", running: true };
}

// Kill an entire Windows process tree rooted at `pid`.
// Returns true if taskkill reported success.
function taskkillTree(pid) {
  try {
    const res = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    return res.status === 0;
  } catch (_) {
    return false;
  }
}

// Last-resort cleanup: kill stray hub processes, in case the tracked PID
// went stale (PyInstaller bootloader spawns a child, Flask/Werkzeug reloader,
// shell wrapper, etc.). Packaged mode -> nvidia_hub.exe; dev mode ->
// python.exe running OUR nvidia_hub.py (matched precisely so unrelated
// Python interpreters are never touched).
function killStragglers() {
  if (process.platform !== "win32") return;

  // Packaged binary — safe to kill by image name.
  try {
    spawnSync("taskkill", ["/IM", "nvidia_hub.exe", "/F"], { windowsHide: true, stdio: "ignore" });
  } catch (_) {}

  // Dev mode: find python.exe whose command line contains nvidia_hub.py.
  // Use wmic CommandLine match (precise, no orphan kills).
  try {
    const wmic = spawnSync(
      "wmic",
      ["process", "where", "name='python.exe' and CommandLine like '%nvidia_hub.py%'", "get", "ProcessId", "/format:list"],
      { windowsHide: true, encoding: "utf8" }
    );
    if (wmic.status === 0 && wmic.stdout) {
      for (const line of wmic.stdout.split(/\r?\n/)) {
        const m = line.match(/ProcessId=(\d+)/i);
        if (m) {
          try {
            spawnSync("taskkill", ["/PID", m[1], "/T", "/F"], { windowsHide: true, stdio: "ignore" });
          } catch (_) {}
        }
      }
    }
  } catch (_) {}
}

function stopHub() {
  if (!isHubRunning()) {
    hubProcess = null;
    broadcastStatus();
    return { ok: true, message: "Hub is not running", running: false };
  }

  pushLog("info", "Stopping hub…");
  const proc = hubProcess;

  try {
    if (process.platform === "win32") {
      // Kill the whole tree (Flask/Werkzeug can spawn reloader children).
      taskkillTree(proc.pid);
      // Give the OS a moment to reap, then verify the port is actually free.
      spawnSync("timeout", ["/t", "1", "/nobreak"], { windowsHide: true, stdio: "ignore" });
    } else {
      proc.kill("SIGTERM");
      // SIGKILL fallback after 2s if still alive.
      setTimeout(() => {
        if (proc.exitCode === null) proc.kill("SIGKILL");
      }, 2000);
    }
  } catch (err) {
    pushLog("error", `Stop failed: ${err.message}`);
    return { ok: false, message: err.message, running: isHubRunning() };
  }

  // Don't trust .killed/.exitCode alone — external taskkill doesn't flip them
  // and the Flask child can outlive the tracked shell wrapper. Verify the port.
  let config;
  try {
    config = loadConfig();
  } catch (_) {
    config = { host: "127.0.0.1", port: 59714 };
  }
  const stillAlive = isPortInUse(config.host === "0.0.0.0" ? "127.0.0.1" : config.host, config.port);

  if (stillAlive) {
    pushLog("warn", "Port still in use after stop; killing stray processes…");
    killStragglers();
    spawnSync("timeout", ["/t", "1", "/nobreak"], { windowsHide: true, stdio: "ignore" });
  }

  hubProcess = null;
  pushLog("success", "Hub stopped");
  broadcastStatus();
  return { ok: true, message: "Hub stopped", running: false };
}

// Sync port probe on Windows via netstat; falls back to true (assume alive)
// on non-Windows so we never skip the straggler-kill fallback there.
function isPortInUse(host, port) {
  if (process.platform !== "win32") return true;
  try {
    const res = spawnSync("netstat", ["-ano", "-p", "TCP"], {
      windowsHide: true,
      encoding: "utf8",
    });
    if (res.status !== 0 || !res.stdout) return true;
    const listenRe = new RegExp(
      `\\s+${host === "0.0.0.0" ? "0\\.0\\.0\\.0" : host.replace(/\./g, "\\.")}:${port}\\s.*LISTENING\\s+(\\d+)`,
      "i"
    );
    return listenRe.test(res.stdout);
  } catch (_) {
    return true; // be safe: run the fallback kill
  }
}

function probeHealth(config) {
  return new Promise((resolve) => {
    const host = config.host === "0.0.0.0" ? "127.0.0.1" : config.host;
    const port = config.port;
    const req = http.get(
      { host, port, path: "/health", timeout: 2500 },
      (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            resolve({ ok: res.statusCode === 200, data: JSON.parse(body), statusCode: res.statusCode });
          } catch {
            resolve({ ok: false, data: null, statusCode: res.statusCode });
          }
        });
      }
    );
    req.on("error", () => resolve({ ok: false, data: null, statusCode: 0 }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, data: null, statusCode: 0 });
    });
  });
}

function hubHttpJson(config, { method = "GET", path = "/usage", body = null, timeout = 4000 } = {}) {
  return new Promise((resolve) => {
    const host = config.host === "0.0.0.0" ? "127.0.0.1" : config.host;
    const port = config.port;
    const payload = body != null ? Buffer.from(JSON.stringify(body), "utf8") : null;
    const req = http.request(
      {
        host,
        port,
        path,
        method,
        timeout,
        headers: payload
          ? {
              "Content-Type": "application/json",
              "Content-Length": payload.length,
            }
          : {},
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => {
          try {
            resolve({
              ok: res.statusCode >= 200 && res.statusCode < 300,
              data: raw ? JSON.parse(raw) : null,
              statusCode: res.statusCode,
            });
          } catch {
            resolve({ ok: false, data: null, statusCode: res.statusCode, error: "Invalid JSON" });
          }
        });
      }
    );
    req.on("error", (err) => resolve({ ok: false, data: null, statusCode: 0, error: err.message }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, data: null, statusCode: 0, error: "timeout" });
    });
    if (payload) req.write(payload);
    req.end();
  });
}

async function getUsage() {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    return { ok: false, error: err.message, session: null, all_time: null };
  }
  const res = await hubHttpJson(config, { method: "GET", path: "/usage" });
  if (!res.ok || !res.data) {
    return {
      ok: false,
      error: res.error || "Hub offline or usage unavailable",
      session: null,
      all_time: null,
    };
  }
  return { ok: true, error: null, ...res.data };
}

async function resetUsage(scope = "session") {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    return { ok: false, error: err.message };
  }
  const res = await hubHttpJson(config, {
    method: "POST",
    path: "/usage/reset",
    body: { scope },
  });
  if (!res.ok || !res.data) {
    return { ok: false, error: res.error || "Reset failed — is the hub running?" };
  }
  return { ok: true, error: null, ...res.data };
}

async function getStatus() {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    return {
      running: false,
      healthy: false,
      processAlive: isHubRunning(),
      health: null,
      config: null,
      error: err.message,
      endpoint: null,
      endpoints: null,
    };
  }

  const processAlive = isHubRunning();
  const health = await probeHealth(config);
  const host = config.host === "0.0.0.0" ? "127.0.0.1" : config.host;
  const base = `http://${host}:${config.port}`;

  const providerSummaries = {};
  for (const [pid, p] of Object.entries(config.providers || {})) {
    providerSummaries[pid] = {
      label: p.label,
      base_url: p.base_url,
      keys_count: (p.keys || []).length,
      endpoint: `${base}/${pid}/v1`,
    };
  }

  const defaultProvider = config.default_provider;
  const defaultKeys =
    config.providers?.[defaultProvider]?.keys?.length ?? 0;

  return {
    running: processAlive || health.ok,
    healthy: health.ok,
    processAlive,
    health: health.data,
    config: {
      host: config.host,
      port: config.port,
      timeout: config.timeout,
      default_provider: defaultProvider,
      providers: providerSummaries,
      proxy_enabled: config.proxy_enabled,
      proxy_type: config.proxy_type,
      proxy_host: config.proxy_host,
      proxy_port: config.proxy_port,
      anonymous_enabled: Boolean(config.anonymous_enabled),
      keys_count: defaultKeys,
    },
    endpoint: `${base}/v1`,
    endpoints: {
      default: `${base}/v1`,
      ...Object.fromEntries(
        Object.keys(config.providers || {}).map((pid) => [pid, `${base}/${pid}/v1`])
      ),
    },
    error: null,
  };
}

function broadcastStatus() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  getStatus().then((status) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("hub:status", status);
    }
  });
}

function createWindow() {
  const settings = loadAppSettings();
  const bounds = settings.windowBounds || { width: 1280, height: 860 };

  mainWindow = new BrowserWindow({
    width: bounds.width || 1280,
    height: bounds.height || 860,
    minWidth: 1024,
    minHeight: 700,
    x: bounds.x,
    y: bounds.y,
    show: false,
    frame: false,
    titleBarStyle: "hidden",
    icon: path.join(ROOT, "src", "Apihub.ico"),
    backgroundColor: ({
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
    })[settings.theme] || "#07090d",
    transparent: false,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(ROOT, "src", "index.html"));

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.on("close", () => {
    if (!mainWindow) return;
    const b = mainWindow.getBounds();
    saveAppSettings({ windowBounds: b });
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function registerIpc() {
  ipcMain.handle("window:minimize", () => mainWindow?.minimize());
  ipcMain.handle("window:maximize", () => {
    if (!mainWindow) return false;
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
      return false;
    }
    mainWindow.maximize();
    return true;
  });
  ipcMain.handle("window:close", () => mainWindow?.close());
  ipcMain.handle("window:isMaximized", () => mainWindow?.isMaximized() ?? false);

  ipcMain.handle("app:getSettings", () => loadAppSettings());
  ipcMain.handle("app:setTheme", (_e, theme) => {
    const next = saveAppSettings({ theme });
    nativeTheme.themeSource = "dark";
    return next;
  });

  ipcMain.handle("config:get", () => {
    return serializeConfigForUi(loadConfig());
  });

  ipcMain.handle("config:save", (_e, payload) => {
    const current = loadConfig();
    const next = {
      default_provider: payload.default_provider ?? current.default_provider,
      providers: { ...current.providers },
      host: payload.host ?? current.host,
      port: Number(payload.port ?? current.port),
      timeout: Number(payload.timeout ?? current.timeout),
      proxy_enabled: Boolean(
        payload.proxy_enabled !== undefined ? payload.proxy_enabled : current.proxy_enabled
      ),
      proxy_type: payload.proxy_type ?? current.proxy_type,
      proxy_host: payload.proxy_host ?? current.proxy_host,
      proxy_port: Number(payload.proxy_port ?? current.proxy_port),
      anonymous_enabled: Boolean(
        payload.anonymous_enabled !== undefined
          ? payload.anonymous_enabled
          : current.anonymous_enabled
      ),
      github_proxy_enabled: Boolean(
        payload.github_proxy_enabled !== undefined
          ? payload.github_proxy_enabled
          : current.github_proxy_enabled
      ),
      github_repo: payload.github_repo ?? current.github_repo ?? "Amiro3D/api-hub",
      github_proxy_url: current.github_proxy_url || "",
      github_proxy_status: current.github_proxy_status || "stopped",
    };

    // Merge providers payload
    if (payload.providers && typeof payload.providers === "object") {
      for (const [pid, pdata] of Object.entries(payload.providers)) {
        const existing = next.providers[pid] || PROVIDER_DEFAULTS[pid] || {
          label: pid,
          base_url: "",
          keys: [],
        };
        next.providers[pid] = {
          label: pdata.label || existing.label || pid,
          base_url: normalizeBaseUrl(
            pdata.base_url !== undefined ? pdata.base_url : existing.base_url
          ),
          keys:
            pdata.keys !== undefined
              ? (Array.isArray(pdata.keys) ? pdata.keys : []).filter(Boolean)
              : existing.keys || [],
        };
      }
    }

    // Convenience: update single provider keys
    if (payload.provider_id && payload.keys !== undefined) {
      const pid = payload.provider_id;
      if (!next.providers[pid]) {
        next.providers[pid] = {
          ...(PROVIDER_DEFAULTS[pid] || { label: pid, base_url: "", keys: [] }),
        };
      }
      next.providers[pid].keys = (Array.isArray(payload.keys) ? payload.keys : []).filter(Boolean);
    }

    // Convenience: update single provider base_url
    if (payload.provider_id && payload.base_url !== undefined) {
      const pid = payload.provider_id;
      if (!next.providers[pid]) {
        next.providers[pid] = {
          ...(PROVIDER_DEFAULTS[pid] || { label: pid, base_url: "", keys: [] }),
        };
      }
      next.providers[pid].base_url = normalizeBaseUrl(payload.base_url);
    }

    if (!Number.isFinite(next.port) || next.port < 1 || next.port > 65535) {
      throw new Error("Port must be between 1 and 65535");
    }
    if (!Number.isFinite(next.timeout) || next.timeout < 1) {
      throw new Error("Timeout must be a positive number");
    }
    if (!next.providers[next.default_provider]) {
      throw new Error("Invalid default provider");
    }

    // At least one provider must have keys — unless a keyless provider (e.g.
    // kilo free tier) is configured, which works with zero keys.
    const totalKeys = Object.values(next.providers).reduce(
      (n, p) => n + ((p.keys || []).length),
      0
    );
    const hasKeyless = Object.keys(next.providers).some((pid) =>
      KEYLESS_PROVIDERS.includes(pid)
    );
    if (totalKeys === 0 && !hasKeyless) {
      throw new Error("At least one API key is required across providers");
    }

    const saved = saveConfig(next);
    pushLog("success", "Configuration saved");
    broadcastStatus();
    return serializeConfigForUi(saved);
  });

  ipcMain.handle("hub:start", () => startHub());
  ipcMain.handle("hub:stop", () => stopHub());
  ipcMain.handle("hub:restart", () => {
    stopHub();
    return new Promise((resolve) => {
      setTimeout(() => resolve(startHub()), 600);
    });
  });
  ipcMain.handle("hub:status", () => getStatus());
  ipcMain.handle("hub:usage", () => getUsage());
  ipcMain.handle("hub:resetUsage", (_e, scope) => resetUsage(scope || "session"));
  ipcMain.handle("hub:logs", () => logBuffer.slice());
  ipcMain.handle("hub:clearLogs", () => {
    logBuffer = [];
    return true;
  });

  ipcMain.handle("githubProxy:status", async () => {
    let config;
    try {
      config = loadConfig();
    } catch (err) {
      return { ok: false, error: err.message, status: "stopped", tunnel_url: "" };
    }
    const res = await hubHttpJson(config, { method: "GET", path: "/github-proxy/status" });
    if (res.ok && res.data) {
      return { ok: true, ...res.data };
    }
    const repo = config.github_repo || "Amiro3D/api-hub";
    return new Promise((resolve) => {
      exec(`gh issue view 1 --repo "${repo}" --json title`, { timeout: 5000 }, (err, stdout) => {
        let tunnel_url = "";
        let status = "stopped";
        if (!err && stdout) {
          try {
            const data = JSON.parse(stdout);
            const title = (data.title || "").trim();
            if (title.startsWith("https://") && title.includes("trycloudflare.com")) {
              tunnel_url = title;
              status = "running";
            }
          } catch (_) {}
        }
        resolve({ ok: true, status, tunnel_url, repo, enabled: Boolean(config.github_proxy_enabled) });
      });
    });
  });

  ipcMain.handle("githubProxy:start", async () => {
    let config;
    try {
      config = loadConfig();
    } catch (err) {
      return { ok: false, message: err.message };
    }
    const repo = config.github_repo || "Amiro3D/api-hub";
    return new Promise((resolve) => {
      exec(`gh workflow run proxy.yml --repo "${repo}"`, { timeout: 10000 }, (err, stdout, stderr) => {
        if (err) {
          resolve({ ok: false, message: stderr || stdout || err.message });
        } else {
          resolve({ ok: true, message: "GitHub Action runner started" });
        }
      });
    });
  });

  ipcMain.handle("githubProxy:stop", async () => {
    let config;
    try {
      config = loadConfig();
    } catch (err) {
      return { ok: false, message: err.message };
    }
    const repo = config.github_repo || "Amiro3D/api-hub";
    return new Promise((resolve) => {
      exec(`gh issue edit 1 --repo "${repo}" --title "STOPPED" --body "Stopped by user"`, { timeout: 8000 }, () => {
        resolve({ ok: true, message: "GitHub Action runner stopped" });
      });
    });
  });

  ipcMain.handle("shell:openExternal", (_e, url) => shell.openExternal(url));
  ipcMain.handle("shell:openConfig", () => shell.showItemInFolder(CONFIG_PATH));
}

app.whenReady().then(() => {
  ensurePackagedConfig();

  // Migrate legacy config on first launch
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const cfg = loadConfig();
      saveConfig(cfg);
    }
  } catch (err) {
    console.error("Config migrate failed:", err);
  }

  registerIpc();
  createWindow();

  setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) broadcastStatus();
  }, 6000);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  stopHub();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopHub();
});
