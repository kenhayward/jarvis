"use strict";

// Starting with Windows. Kept free of Electron so node:test can check the
// decisions; main.js does the calling.
//
// On Windows app.setLoginItemSettings writes a Run entry in the user's
// registry hive. For an UNPACKAGED app, execPath is electron.exe, which on
// its own starts Electron's default app -- so the entry must carry this
// app's directory. And a launch from login starts hidden, which the entry
// says with --hidden.

const HIDDEN_FLAG = "--hidden";

// The registry value's name. Left to Electron it is "electron.app.Electron",
// shared by every unpackaged Electron app: another one would overwrite it,
// and Task Manager's Startup tab would list it as "Electron".
const LOGIN_NAME = "JARVIS";

// Where the checkbox can work. macOS login items take no arguments, so an
// unpackaged app cannot name itself in one; there the checkbox is withdrawn
// rather than shown doing nothing.
function startAtLoginSupported(platform) {
  return platform === "win32";
}

function loginItem(execPath, appPath) {
  return { path: execPath, args: [appPath, HIDDEN_FLAG], name: LOGIN_NAME };
}

function launchedAtLogin(argv) {
  return argv.includes(HIDDEN_FLAG);
}

// Whether Windows will start JARVIS at login, from getLoginItemSettings().
// Not its `openAtLogin`: measured on Electron 44, that is true for ANY Run
// entry with the same path and args, whatever its name -- it stayed true
// after our own entry had been removed. So: our entry, by name, and
// enabled -- Task Manager's Startup tab can switch it off without deleting it.
function startsAtLogin(settings) {
  const items = (settings && settings.launchItems) || [];
  return items.some((item) => item.name === LOGIN_NAME && item.enabled);
}

module.exports = {
  HIDDEN_FLAG, LOGIN_NAME, startAtLoginSupported, loginItem, launchedAtLogin, startsAtLogin,
};
