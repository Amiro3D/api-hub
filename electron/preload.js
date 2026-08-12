const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("nvidiaHub", {
  // Window chrome
  minimize: () => ipcRenderer.invoke("window:minimize"),
  maximize: () => ipcRenderer.invoke("window:maximize"),
  close: () => ipcRenderer.invoke("window:close"),
  isMaximized: () => ipcRenderer.invoke("window:isMaximized"),

  // App settings
  getSettings: () => ipcRenderer.invoke("app:getSettings"),
  setTheme: (theme) => ipcRenderer.invoke("app:setTheme", theme),

  // Config
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (payload) => ipcRenderer.invoke("config:save", payload),

  // Hub process
  startHub: () => ipcRenderer.invoke("hub:start"),
  stopHub: () => ipcRenderer.invoke("hub:stop"),
  restartHub: () => ipcRenderer.invoke("hub:restart"),
  getStatus: () => ipcRenderer.invoke("hub:status"),
  getUsage: () => ipcRenderer.invoke("hub:usage"),
  resetUsage: (scope) => ipcRenderer.invoke("hub:resetUsage", scope),
  getLogs: () => ipcRenderer.invoke("hub:logs"),
  clearLogs: () => ipcRenderer.invoke("hub:clearLogs"),

  // GitHub Proxy
  startGithubProxy: () => ipcRenderer.invoke("githubProxy:start"),
  stopGithubProxy: () => ipcRenderer.invoke("githubProxy:stop"),
  getGithubProxyStatus: () => ipcRenderer.invoke("githubProxy:status"),

  // Shell
  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),
  openConfigFolder: () => ipcRenderer.invoke("shell:openConfig"),

  // Events
  onStatus: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on("hub:status", handler);
    return () => ipcRenderer.removeListener("hub:status", handler);
  },
  onLog: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on("hub:log", handler);
    return () => ipcRenderer.removeListener("hub:log", handler);
  },
});
