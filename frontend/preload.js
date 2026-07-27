// Minimal preload — the renderer talks to the Python backend over plain HTTP
// (localhost:8000), so we don't need to expose Node APIs directly.
// Kept here so it's easy to add real desktop-API bridges (native dialogs,
// tray icon, etc.) later without touching the renderer's fetch-based code.

const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('luna', {
  platform: process.platform,
});
