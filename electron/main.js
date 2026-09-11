"use strict";
const { app, BrowserWindow, Menu, Tray, dialog, session, shell, systemPreferences } = require("electron");
const path = require("node:path");
const { createSupervisor } = require("./server");
const { sameOrigin, grantsPermission } = require("./policy");

const ORIGIN = process.env.JARVIS_ORIGIN || "http://127.0.0.1:8340";
const REPO_ROOT = path.resolve(__dirname, "..");
const log = (m) => console.log(`[jarvis] ${m}`);

// HTTP and not HTTPS, deliberately. The certificates exist for one reason --
// frontend/vite.config.ts hard-codes an HTTPS proxy target -- and there is no
// Vite here. `http://127.0.0.1` is a secure context by the same rule that
// makes localhost one, so getUserMedia works and the openssl step disappears
// from this path. It does NOT disappear from the dev-server workflow, and
// since that leaves the certs beside server.py, the supervisor passes
// --no-ssl.

// One application per machine. A second copy would probe, find the first
// one's server, and attach to it; quitting the first would then kill the
// server out from under the second. The second copy shows the first instead.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  let win = null;
  let tray = null;        // held here so it is never garbage-collected away
  // The one flag that separates "the user closed the window" from "the
  // application is quitting". It is set in before-quit, which every quit
  // passes through -- the tray's Quit, Cmd+Q, anything that calls
  // app.quit(). Set only by the tray, any other quit would stop the server
  // in before-quit and then have the window's close handler cancel the quit
  // by hiding: a hidden JARVIS with no server behind it.
  let reallyQuitting = false;
  let toldAboutTheTray = false;
  const supervisor = createSupervisor({ repoRoot: REPO_ROOT, origin: ORIGIN, deps: { log } });

  function showWindow() {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }

  app.on("second-instance", showWindow);

  function createTray() {
    tray = new Tray(path.join(__dirname, "tray-icon.png"));
    tray.setToolTip("JARVIS (listening)");
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: "Show JARVIS", click: showWindow },
      { type: "separator" },
      // Quit must be findable. An application a person cannot work out how
      // to exit is worse than one that simply closes when you close it.
      { label: "Quit JARVIS", click: () => app.quit() },
    ]));
    tray.on("double-click", showWindow);
  }

  // The first time the window is closed, say where JARVIS went. Closing
  // hides an application that still holds the microphone, and the person
  // who closed it has every reason to think it has gone. Once per run, and
  // silent -- a notice about listening should not make a sound. The balloon
  // is Windows-only; macOS gets nothing here yet.
  function explainTheTray() {
    if (toldAboutTheTray || !tray || process.platform !== "win32") return;
    toldAboutTheTray = true;
    tray.displayBalloon({
      title: "JARVIS is still listening",
      content: "Closing the window hides it. To quit, use the tray icon.",
      noSound: true,
    });
  }

  function grantMicrophone() {
    // Mandatory: Electron DENIES media unless this handler exists (measured
    // in 4-zero), in a way indistinguishable from the macOS TCC case below.
    // Every decision is logged -- the policy relies on Electron reporting the
    // requesting URL and the media types, and a wrong guess about either
    // would be a deaf JARVIS with nothing on screen to say why.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback, details) => {
      const granted = grantsPermission(permission, details, ORIGIN);
      log(`permission ${permission} from ${details && details.requestingUrl} ` +
          `mediaTypes=${JSON.stringify(details && details.mediaTypes)} -> ` +
          `${granted ? "granted" : "DENIED"}`);
      callback(granted);
    });
  }

  async function askMacOS() {
    // macOS only, and UNVERIFIED -- written from documentation on a Windows
    // box, which is the condition that cost this port two wrong premises. TCC
    // is a SECOND gate the handler above does not satisfy; a packaged build
    // also needs NSMicrophoneUsageDescription in its Info.plist. Install the
    // handler, still fail, and there is no way to tell which gate is shut.
    if (process.platform !== "darwin") return;
    try {
      const status = systemPreferences.getMediaAccessStatus("microphone");
      log(`macOS microphone TCC status: ${status}`);
      if (status !== "granted") {
        log(`askForMediaAccess -> ${await systemPreferences.askForMediaAccess("microphone")}`);
      }
    } catch (e) {
      log(`TCC probe failed: ${e.message}`);
    }
  }

  // The window holds the microphone, so it shows JARVIS and nothing else. A
  // link off the JARVIS origin goes to the user's own browser, and only an
  // http(s) one -- shell.openExternal hands any scheme to the OS.
  function openOutside(url) {
    try {
      const { protocol } = new URL(url);
      if (protocol === "http:" || protocol === "https:") shell.openExternal(url);
    } catch {
      // not a URL; nothing to open
    }
  }

  function createWindow() {
    win = new BrowserWindow({
      width: 1100,
      height: 800,
      title: "JARVIS",
      backgroundColor: "#111111",
      webPreferences: {
        preload: path.join(__dirname, "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        // REQUIRED for tray residency. Measured in Task 1: a hidden window with
        // the default (true) captured 67.1% of its audio over ten minutes, the
        // same window visible captured 100.0%, and with this set to false it
        // captured 95.7%. Throttling starts within ~30s of hiding. Without this
        // line, closing JARVIS to the tray loses a third of what is said to it,
        // and it transcribes as garbage rather than failing cleanly.
        backgroundThrottling: false,
      },
    });
    win.webContents.on("will-navigate", (event, url) => {
      if (sameOrigin(url, ORIGIN)) return;
      event.preventDefault();
      openOutside(url);
    });
    win.webContents.setWindowOpenHandler(({ url }) => {
      openOutside(url);
      return { action: "deny" };
    });
    // Closing HIDES. The server keeps running and JARVIS keeps listening --
    // the whole point of tray residency, and only sound because Task 1
    // measured audio surviving a hidden window (with backgroundThrottling
    // off, above).
    win.on("close", (event) => {
      if (reallyQuitting) return;
      event.preventDefault();
      win.hide();
      explainTheTray();
    });
    // Windows logoff and shutdown do NOT emit before-quit (Electron's
    // documentation; not exercised here), so the window hears it instead --
    // without this, the close handler above would hide and hold up the
    // session ending.
    win.on("session-end", () => { reallyQuitting = true; });
    win.on("closed", () => { win = null; });
    win.loadURL(ORIGIN);
    return win;
  }

  app.whenReady().then(async () => {
    grantMicrophone();
    await askMacOS();

    const result = await supervisor.start();
    log(`server: ${result.state} -- ${result.detail}`);

    if (result.state === "occupied" || result.state === "failed") {
      dialog.showErrorBox("JARVIS could not start", result.detail);
      app.quit();
      return;
    }
    createWindow();
    createTray();
  });

  // Deliberately does nothing. Closing the window hides it; the application
  // exits through the tray's Quit, or any other app.quit().
  app.on("window-all-closed", () => {});

  app.on("before-quit", () => {
    reallyQuitting = true;
    supervisor.stop();
  });
}
