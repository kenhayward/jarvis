const { test } = require("node:test");
const assert = require("node:assert");
const { sttWarning } = require("../backend");

const PYTHON = "C:\\repo\\.venv\\Scripts\\python.exe";
// The shape /api/settings/status reports, as far as this reads it.
const status = (backend, whisperReady) => ({
  stt_backend: backend,
  stt_backends_ready: { browser: true, whisper: whisperReady },
});

// Measured in 4-zero: webkitSpeechRecognition is DEFINED in Electron and
// fails at runtime with error=network. A browser backend here looks alive
// and never returns a word.
test("warns when the browser's recogniser is configured", () => {
  const w = sttWarning(status("browser", true), PYTHON);
  assert.ok(w && /JARVIS_STT_BACKEND=whisper/.test(w), w);
});

test("says nothing when whisper is configured and ready", () => {
  assert.strictEqual(sttWarning(status("whisper", true), PYTHON), null);
});

// stt.transcribe returns None for every utterance when the package or the
// model is missing, and says so only in the server's log -- which a window
// the application started gives nobody a reason to read.
test("warns when whisper is configured but not installed", () => {
  const w = sttWarning(status("whisper", false), PYTHON);
  assert.ok(w && /requirements-stt\.txt/.test(w), w);
  assert.ok(w.includes(`${PYTHON} -m pip install -r requirements-stt.txt`), w);
  assert.ok(w.includes("WhisperModel("), w);
});

test("the commands are quoted when the interpreter's path has a space", () => {
  const spaced = "C:\\Users\\A Person\\jarvis\\.venv\\Scripts\\python.exe";
  const w = sttWarning(status("whisper", false), spaced);
  assert.ok(w.includes(`"${spaced}" -m pip install`), w);
});

test("says nothing rather than guessing when readiness is not reported", () => {
  assert.strictEqual(sttWarning({ stt_backend: "whisper" }, PYTHON), null);
});

test("says nothing rather than guessing when the status is unreadable", () => {
  assert.strictEqual(sttWarning(null, PYTHON), null);
  assert.strictEqual(sttWarning({}, PYTHON), null);
  assert.strictEqual(sttWarning({ stt_backend: 42 }, PYTHON), null);
});
