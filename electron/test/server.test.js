const { test } = require("node:test");
const assert = require("node:assert");
const { EventEmitter } = require("node:events");
const { createSupervisor } = require("../server");

const REPO = "C:\repo";
const ORIGIN = "http://127.0.0.1:8340";
const PYTHON = "C:\repo\.venv\Scripts\python.exe";

// A stand-in child process: a real EventEmitter, because the supervisor
// listens for "exit" and "error" and a child that cannot emit them would let
// those paths go untested.
function fakeChild(killed) {
  const child = new EventEmitter();
  child.pid = 4242;
  child.kill = (sig) => { killed.push(sig); return true; };
  return child;
}

function deps(overrides = {}) {
  const killed = [];
  const spawned = [];
  const d = {
    findPython: () => PYTHON,
    probe: async () => "nothing",
    waitForJarvis: async () => true,
    spawn: (command, args, options) => {
      spawned.push({ command, args, options });
      d.child = fakeChild(killed);
      return d.child;
    },
    killed,
    spawned,
    ...overrides,
  };
  return d;
}

const supervise = (d, origin = ORIGIN) => createSupervisor({ repoRoot: REPO, origin, deps: d });

test("attaches to a JARVIS already running, and spawns nothing", async () => {
  const d = deps({ probe: async () => "jarvis" });
  const s = supervise(d);
  const r = await s.start();
  assert.strictEqual(r.state, "attached");
  assert.deepStrictEqual(d.spawned, []);
  assert.strictEqual(s.startedByUs, false);
});

test("stop() does NOT kill a server it attached to", async () => {
  const d = deps({ probe: async () => "jarvis" });
  const s = supervise(d);
  await s.start();
  s.stop();
  assert.deepStrictEqual(d.killed, []);
});

test("spawns when nothing is listening", async () => {
  const d = deps();
  const s = supervise(d);
  const r = await s.start();
  assert.strictEqual(r.state, "started");
  assert.strictEqual(s.startedByUs, true);
});

// --no-ssl because server.py turns HTTPS on by itself when the dev
// workflow's certs are beside it, and this window only speaks http://.
// Host and port come from the origin, so the server listens where the
// window and the health poll will look.
test("starts the venv's server.py over plain HTTP, where the origin says", async () => {
  const d = deps();
  await supervise(d, "http://127.0.0.1:8350").start();
  assert.strictEqual(d.spawned.length, 1);
  const { command, args, options } = d.spawned[0];
  assert.strictEqual(command, PYTHON);
  assert.deepStrictEqual(args, ["server.py", "--host", "127.0.0.1", "--port", "8350", "--no-ssl"]);
  assert.strictEqual(options.cwd, REPO);
});

test("stop() kills a server it started", async () => {
  const d = deps();
  const s = supervise(d);
  await s.start();
  s.stop();
  assert.strictEqual(d.killed.length, 1);
});

test("refuses a port held by a stranger rather than guessing", async () => {
  const d = deps({ probe: async () => "stranger" });
  const r = await supervise(d).start();
  assert.strictEqual(r.state, "occupied");
  assert.deepStrictEqual(d.spawned, []);
});

// Measured in Task 3: a developer's own JARVIS, started with the certs,
// serves HTTPS and probes as a stranger. That is the likeliest thing on
// this port, so the refusal says so instead of only "not JARVIS".
test("an occupied port names the likeliest occupant", async () => {
  const d = deps({ probe: async () => "stranger" });
  const r = await supervise(d).start();
  assert.match(r.detail, /HTTPS/);
});

test("reports a missing interpreter instead of spawning nothing", async () => {
  const d = deps({ findPython: () => null });
  const r = await supervise(d).start();
  assert.strictEqual(r.state, "failed");
  assert.match(r.detail, /interpreter/i);
  assert.deepStrictEqual(d.spawned, []);
});

test("a server that never becomes healthy is a failure, not a hang", async () => {
  const d = deps({ waitForJarvis: async () => false });
  const r = await supervise(d).start();
  assert.strictEqual(r.state, "failed");
  assert.match(r.detail, /did not answer/i);
});

test("a server it gave up on is killed, not left running behind the failure", async () => {
  const d = deps({ waitForJarvis: async () => false });
  await supervise(d).start();
  assert.strictEqual(d.killed.length, 1);
});

// A missing requirement dies with an ImportError in about a second. Waiting
// out the whole health deadline for a process that is already gone would
// turn that into thirty seconds of nothing and a vaguer message.
test("a server that exits before answering fails at once, with its exit code", async () => {
  // Dies while being waited on, and the wait itself never ends.
  const d = deps({ waitForJarvis: () => {
    setImmediate(() => d.child.emit("exit", 1, null));
    return new Promise(() => {});
  } });
  const r = await supervise(d).start();
  assert.strictEqual(r.state, "failed");
  assert.match(r.detail, /exited.*1/);
});

// An unhandled "error" on a ChildProcess is thrown -- in Electron's main
// process, that is the application crashing.
test("a spawn error is a failure, not a crash", async () => {
  // Emitted on a later tick, as a real failed spawn reports it.
  const d = deps({ waitForJarvis: () => {
    setImmediate(() => d.child.emit("error", Object.assign(new Error("spawn EACCES"), { code: "EACCES" })));
    return new Promise(() => {});
  } });
  const r = await supervise(d).start();
  assert.strictEqual(r.state, "failed");
  assert.match(r.detail, /EACCES/);
});
