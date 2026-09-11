const { test } = require("node:test");
const assert = require("node:assert");
const { sameOrigin, grantsPermission } = require("../policy");

const ORIGIN = "http://127.0.0.1:8340";

test("the JARVIS page is its own origin, at any path", () => {
  assert.strictEqual(sameOrigin("http://127.0.0.1:8340/", ORIGIN), true);
  assert.strictEqual(sameOrigin("http://127.0.0.1:8340/dashboard?tab=runs", ORIGIN), true);
});

// Compared as parsed origins, never as string prefixes: a prefix check
// passes the second of these.
test("a look-alike host is not the JARVIS origin", () => {
  assert.strictEqual(sameOrigin("https://example.com/", ORIGIN), false);
  assert.strictEqual(sameOrigin("http://127.0.0.1:8340.example.com/", ORIGIN), false);
});

test("another port or scheme on the same machine is not the JARVIS origin", () => {
  assert.strictEqual(sameOrigin("http://127.0.0.1:5173/", ORIGIN), false);
  assert.strictEqual(sameOrigin("https://127.0.0.1:8340/", ORIGIN), false);
});

test("something that is not a URL is nobody's origin", () => {
  assert.strictEqual(sameOrigin("not a url", ORIGIN), false);
  assert.strictEqual(sameOrigin(undefined, ORIGIN), false);
});

// The handler Electron needs is a yes to media -- measured in 4-zero,
// without it getUserMedia fails -- but a yes to the JARVIS page's
// microphone only. `details` is what Electron passes the handler:
// requestingUrl, and for "media" the mediaTypes asked for.
const jarvisPage = (mediaTypes) => ({ requestingUrl: "http://127.0.0.1:8340/", mediaTypes });

test("the JARVIS page gets the microphone", () => {
  assert.strictEqual(grantsPermission("media", jarvisPage(["audio"]), ORIGIN), true);
});

test("any other page does not get the microphone", () => {
  const details = { requestingUrl: "https://example.com/", mediaTypes: ["audio"] };
  assert.strictEqual(grantsPermission("media", details, ORIGIN), false);
});

test("not even the JARVIS page gets the camera", () => {
  assert.strictEqual(grantsPermission("media", jarvisPage(["video"]), ORIGIN), false);
  assert.strictEqual(grantsPermission("media", jarvisPage(["audio", "video"]), ORIGIN), false);
});

test("a media request that does not say what it wants is refused", () => {
  assert.strictEqual(grantsPermission("media", jarvisPage(undefined), ORIGIN), false);
  assert.strictEqual(grantsPermission("media", jarvisPage([]), ORIGIN), false);
});

test("the JARVIS page gets nothing else it did not need", () => {
  for (const p of ["geolocation", "notifications", "clipboard-read", "openExternal"]) {
    assert.strictEqual(grantsPermission(p, jarvisPage(undefined), ORIGIN), false, p);
  }
});
