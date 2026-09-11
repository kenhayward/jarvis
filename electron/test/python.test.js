const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { findPython } = require("../python");

function tempRepo() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-plan-"));
}

test("finds the Windows interpreter", () => {
  const root = tempRepo();
  fs.mkdirSync(path.join(root, ".venv", "Scripts"), { recursive: true });
  const exe = path.join(root, ".venv", "Scripts", "python.exe");
  fs.writeFileSync(exe, "");
  assert.strictEqual(findPython(root), exe);
});

test("finds the POSIX interpreter", () => {
  const root = tempRepo();
  fs.mkdirSync(path.join(root, ".venv", "bin"), { recursive: true });
  const bin = path.join(root, ".venv", "bin", "python");
  fs.writeFileSync(bin, "");
  assert.strictEqual(findPython(root), bin);
});

test("returns null rather than guessing when there is no venv", () => {
  assert.strictEqual(findPython(tempRepo()), null);
});

test("a DIRECTORY with the interpreter's name is not an interpreter", () => {
  // statSync().isFile(), not existsSync(): a folder called python.exe is not
  // something to spawn, and spawning it fails with an error that names the
  // wrong thing entirely.
  const root = tempRepo();
  fs.mkdirSync(path.join(root, ".venv", "Scripts", "python.exe"), { recursive: true });
  assert.strictEqual(findPython(root), null);
});
