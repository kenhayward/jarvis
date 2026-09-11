const { test } = require("node:test");
const assert = require("node:assert");
const {
  HIDDEN_FLAG, LOGIN_NAME, startAtLoginSupported, loginItem, launchedAtLogin, startsAtLogin,
} = require("../login");

const EXE = "C:\\repo\\electron\\node_modules\\electron\\dist\\electron.exe";
const APP = "C:\\repo\\electron";

// An unpackaged app: electron.exe alone would start Electron's default app,
// so the entry must name THIS app's directory, and mark the launch as hidden.
// And its registry value is called JARVIS: left to Electron it is
// "electron.app.Electron" -- shared by every unpackaged Electron app, so
// another one would overwrite it, and Task Manager would call it "Electron".
test("the login entry launches this app, hidden, under its own name", () => {
  assert.deepStrictEqual(loginItem(EXE, APP),
                         { path: EXE, args: [APP, HIDDEN_FLAG], name: LOGIN_NAME });
  assert.strictEqual(LOGIN_NAME, "JARVIS");
});

// Measured 2026-09-11 on Electron 44: getLoginItemSettings().openAtLogin is
// true if ANY Run entry has the same path and args, whatever its name -- it
// stayed true after our own entry was removed, because another matched. The
// checkbox reads the named list instead: ours, and enabled (Task Manager's
// Startup tab can disable it without deleting it).
const settings = (...items) => ({ openAtLogin: true, launchItems: items });

test("starts at login only for an enabled entry with our name", () => {
  assert.strictEqual(startsAtLogin(settings({ name: "JARVIS", enabled: true })), true);
});

test("another app's entry with the same command is not ours", () => {
  assert.strictEqual(startsAtLogin(settings({ name: "electron.app.Electron", enabled: true })), false);
});

test("our entry disabled in Task Manager does not start at login", () => {
  assert.strictEqual(startsAtLogin(settings({ name: "JARVIS", enabled: false })), false);
});

test("no list at all is not a yes", () => {
  assert.strictEqual(startsAtLogin({ openAtLogin: true }), false);
  assert.strictEqual(startsAtLogin(undefined), false);
});

test("only the exact flag means the launch came from login", () => {
  assert.strictEqual(launchedAtLogin([EXE, APP, "--hidden"]), true);
  assert.strictEqual(launchedAtLogin([EXE, APP]), false);
  assert.strictEqual(launchedAtLogin([EXE, APP, "--hiddenness"]), false);
});

// macOS login items carry no arguments, so for an unpackaged app there is no
// way to name our app in one. A checkbox there would do nothing -- withdrawn,
// not faked.
test("the checkbox exists only where the entry can name the app", () => {
  assert.strictEqual(startAtLoginSupported("win32"), true);
  assert.strictEqual(startAtLoginSupported("darwin"), false);
  assert.strictEqual(startAtLoginSupported("linux"), false);
});
