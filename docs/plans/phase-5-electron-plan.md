# Phase 5: the Electron application — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** JARVIS as a tray-resident desktop application that starts and
supervises its own Python server, with no browser involved.

**Architecture:** An `electron/` package at the repository root, separate from
`frontend/` because it has a different dependency tree and lifecycle. The
Electron main process owns three things — the server's lifecycle, the window,
and the tray. All the real logic (health probing, attach-versus-spawn,
interpreter discovery, kill-only-if-ours) lives in plain JavaScript modules
with **no Electron import**, so it is tested with `node:test` without
launching a GUI. The renderer loads `http://127.0.0.1:8340/`, which is the
server's own page — there is no bundled copy of the frontend.

**Tech Stack:** Electron 44 (already proven in 4-zero), Node's built-in
`node:test` runner (no new test dependency), the existing `server.py`.

**Spec:** [`docs/plans/phase-5-electron.md`](phase-5-electron.md)

> **Where this file lives.** The writing-plans skill's default is
> `docs/superpowers/plans/`. `CLAUDE.md` forbids re-adding that directory to
> this repository — its contents were moved to the ignored `.agents/` — so
> this sits in `docs/plans/` with every other planning document.

## Global Constraints

- **`server.py` is not modified by this phase — with ONE exception, decided
  2026-09-11:** `--no-ssl`, which the supervisor always passes (see Task 4).
  Phase 4 closed; this moves the window the page lives in and nothing else.
- **Electron must never start a second server.** Two servers means two brains
  on one Claude subscription and two writers on one SQLite database.
  `run_store` is not built for that.
- **Kill the server only if this process started it.** Attaching to a
  developer's server and killing it on exit is a nasty surprise.
- **`session.setPermissionRequestHandler` granting `media` is mandatory on
  every platform.** Measured in 4-zero: without it `getUserMedia` fails in a
  way indistinguishable from the macOS TCC case.
- **macOS code goes in marked as UNVERIFIED.** It cannot be tested from the
  Windows box. Write it as a claim, never as a statement of fact.
- **Both names, every platform.** An interpreter or console script is named
  differently per platform; try both rather than branching. Three defects in
  this port have come from assuming one.
- **No new runtime dependency** beyond `electron` itself, which is a
  devDependency. `node:test` is built in.
- Health endpoint contract, verbatim: `GET /api/health` returns
  `{"status": "online", "name": "JARVIS", "version": "0.1.0"}`.
- Default server origin: `http://127.0.0.1:8340`.

---

### Task 1: Does audio survive a hidden window? — **DONE 2026-09-11**

> **Answered: no, not by default.** A hidden window loses a third of its
> audio; `webPreferences.backgroundThrottling: false` removes the
> sustained loss (67.1% -> 95.7%). Full record, including a wrong turn,
> in `phase-5-electron.md`. **Task 5 below has been corrected to carry
> the fix** — without it the tray would silently lose a third of
> everything said to it.

**This task comes first because it can invalidate the design.** The spec names
it as the most likely thing to be wrong and the cheapest to test: Chromium
throttles hidden windows, and if capture stops when the window is hidden then
"closing hides and JARVIS keeps listening" is a promise the platform will not
keep — and the tray decision has to be revisited before anything is built on
it.

Output is an **answer**, not code. Anything built here is throwaway and is
deleted at the end of the task.

**Files:**
- Create (throwaway): `.agents/spikes/hidden-window/` — outside git, deleted after

**Interfaces:**
- Consumes: nothing
- Produces: a recorded finding in `docs/plans/phase-5-electron.md`

- [ ] **Step 1: Scaffold a throwaway Electron app**

```bash
mkdir -p .agents/spikes/hidden-window && cd .agents/spikes/hidden-window
cat > package.json <<'JSON'
{ "name": "hidden-window-spike", "private": true, "main": "main.js" }
JSON
npm install electron --no-save
node node_modules/electron/install.js
```

- [ ] **Step 2: Write the probe**

`main.js`:

```javascript
// THROWAWAY. Does an AudioContext keep delivering samples when the window
// is hidden? If not, the tray decision in phase-5-electron.md is wrong.
const { app, BrowserWindow, session } = require("electron");
const path = require("path");

app.on("ready", () => {
  session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
    console.log(`[main] permission ${permission} -> GRANTED`);
    cb(true);
  });
  const win = new BrowserWindow({ width: 700, height: 500, show: true });
  win.webContents.on("console-message", (_e, _l, m) => console.log(m));
  win.loadFile(path.join(__dirname, "probe.html"));
  // Hide after 6s, leaving 12s of hidden sampling.
  setTimeout(() => { console.log("[main] HIDING WINDOW NOW"); win.hide(); }, 6000);
});
app.on("window-all-closed", () => app.quit());
```

`probe.html`:

```html
<!doctype html><meta charset="utf-8"><title>hidden window spike</title>
<pre id="out">running…</pre><script src="probe.js"></script>
```

`probe.js`:

```javascript
// Report a frame count and peak each second. If the counter stalls after the
// window hides, capture stopped. If it keeps rising but the peak flatlines,
// the samples are dead — which is the same failure wearing a disguise.
const out = document.getElementById("out");
const lines = [];
const say = (s) => { lines.push(s); console.log(s); out.textContent = lines.join("\n"); };

(async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext({ sampleRate: 16000 });
  const src = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  let frames = 0, peak = 0;
  node.onaudioprocess = (e) => {
    frames++;
    for (const s of e.inputBuffer.getChannelData(0)) peak = Math.max(peak, Math.abs(s));
  };
  src.connect(node); node.connect(ctx.destination);
  let last = 0;
  setInterval(() => {
    say(`t+${lines.length}s  frames=${frames} (+${frames - last})  peak=${(peak * 32767) | 0}  ctx=${ctx.state}`);
    last = frames; peak = 0;
  }, 1000);
})();
```

- [ ] **Step 3: Run it and speak throughout**

```bash
node_modules/electron/dist/electron.exe .
```

Speak continuously for the whole 18 seconds, including after
`[main] HIDING WINDOW NOW`. Watch the per-second `+N` frame delta and `peak`.

Expected if the design holds: `+N` stays roughly constant and `peak` keeps
responding to your voice after the window hides.

- [ ] **Step 4: Record the finding in the spec**

Add a section to `docs/plans/phase-5-electron.md` under "What would make this
design wrong", replacing the third bullet with the measured answer — the
per-second frame deltas and peaks before and after hiding, and the verdict.

**If capture stops or the peak flatlines, STOP.** Do not continue to Task 2.
Report it, and the tray decision needs re-deciding — likely to "closing quits"
or to keeping a hidden-but-not-minimised window.

- [ ] **Step 5: Delete the spike and commit the finding**

```bash
rm -rf .agents/spikes/hidden-window
git add docs/plans/phase-5-electron.md
git commit -m "Phase 5 spike: whether audio survives a hidden window"
```

---

### Task 2: Finding the Python interpreter — **DONE 2026-09-11** (`1a57c33`)

**Files:**
- Create: `electron/package.json`
- Create: `electron/python.js`
- Test: `electron/test/python.test.js`

**Interfaces:**
- Consumes: nothing
- Produces: `findPython(repoRoot: string) => string | null` — an absolute path
  to the interpreter, or null. Used by Task 4.

- [ ] **Step 1: Create the package manifest**

`electron/package.json`:

```json
{
  "name": "jarvis-electron",
  "version": "0.1.0",
  "private": true,
  "description": "The JARVIS desktop application.",
  "main": "main.js",
  "scripts": {
    "start": "electron .",
    "test": "node --test test/"
  },
  "devDependencies": {
    "electron": "^44.3.0"
  }
}
```

- [ ] **Step 2: Write the failing test**

`electron/test/python.test.js`:

```javascript
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
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd electron && node --test test/python.test.js
```

Expected: FAIL — `Cannot find module '../python'`.

- [ ] **Step 4: Implement**

`electron/python.js`:

```javascript
"use strict";
const fs = require("node:fs");
const path = require("node:path");

// Both names, on every platform, rather than branching on process.platform.
// A venv's interpreter is `Scripts/python.exe` on Windows and `bin/python`
// on POSIX; the wrong one simply does not exist. This project has had three
// separate defects from assuming one name — `claude.cmd`, a bare `npm`, and
// piper's console script — so the list is two entries and neither is guessed.
const CANDIDATES = [
  path.join(".venv", "Scripts", "python.exe"),
  path.join(".venv", "bin", "python"),
];

function findPython(repoRoot) {
  for (const rel of CANDIDATES) {
    const full = path.join(repoRoot, rel);
    try {
      if (fs.statSync(full).isFile()) return full;
    } catch {
      // not there; try the next
    }
  }
  return null;
}

module.exports = { findPython };
```

- [ ] **Step 5: Run the tests and watch them pass**

```bash
cd electron && node --test test/python.test.js
```

Expected: 3 passing.

- [ ] **Step 6: Commit**

```bash
git add electron/package.json electron/python.js electron/test/python.test.js
git commit -m "electron: find the venv interpreter, both platform names"
```

---

### Task 3: Deciding whether to attach or spawn — **DONE 2026-09-11**

> **Built, with two corrections the code below does not carry** — the
> committed `electron/health.js` and its tests are the truth. Both were found
> by probing a real JARVIS and real sockets rather than fakes, and both tests
> were watched failing against this plan's code first:
>
> 1. **Only a refused connection is "nothing".** A JARVIS started with
>    `cert.pem`/`key.pem` beside `server.py` serves HTTPS, and an `http://`
>    fetch of it throws `UND_ERR_SOCKET`, not `ECONNREFUSED`. The code below
>    catches every throw as "nothing", so a running JARVIS would have been
>    reported as an empty port and Task 4 would have started a second server
>    over it. Any other failure is now "stranger".
> 2. **The probe has a timeout** (`PROBE_TIMEOUT_MS`, 5s; `probe`'s third
>    argument, `waitForJarvis`'s `probeTimeoutMs`). A listener that accepts
>    and never answers held the code below past 15s (undici waits 300s), so
>    `waitForJarvis`'s own deadline never came round.
>
> 10 tests, 7 of them against real listeners on ephemeral ports.

**Files:**
- Create: `electron/health.js`
- Test: `electron/test/health.test.js`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `probe(origin: string, fetchImpl?) => Promise<"jarvis" | "stranger" | "nothing">`
  - `waitForJarvis(origin, {timeoutMs, intervalMs, fetchImpl, sleep}) => Promise<boolean>`

  Used by Task 4.

- [ ] **Step 1: Write the failing test**

`electron/test/health.test.js`:

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const { probe, waitForJarvis } = require("../health");

const ORIGIN = "http://127.0.0.1:8340";
const jarvis = async () => ({ ok: true, json: async () => ({ status: "online", name: "JARVIS", version: "0.1.0" }) });
const stranger = async () => ({ ok: true, json: async () => ({ hello: "i am something else" }) });
const refused = async () => { throw new Error("ECONNREFUSED"); };

test("recognises a JARVIS by name, not merely by answering", async () => {
  assert.strictEqual(await probe(ORIGIN, jarvis), "jarvis");
});

test("a stranger on the port is a stranger, not a JARVIS", async () => {
  assert.strictEqual(await probe(ORIGIN, stranger), "stranger");
});

test("nothing listening is not an error", async () => {
  assert.strictEqual(await probe(ORIGIN, refused), "nothing");
});

test("non-JSON on the port does not throw", async () => {
  const garbage = async () => ({ ok: true, json: async () => { throw new Error("not json"); } });
  assert.strictEqual(await probe(ORIGIN, garbage), "stranger");
});

test("waitForJarvis returns true as soon as one answers", async () => {
  let calls = 0;
  const late = async () => { calls++; return calls < 3 ? refused() : jarvis(); };
  const ok = await waitForJarvis(ORIGIN, {
    timeoutMs: 5000, intervalMs: 1, fetchImpl: late, sleep: async () => {},
  });
  assert.strictEqual(ok, true);
  assert.strictEqual(calls, 3);
});

test("waitForJarvis gives up rather than hanging forever", async () => {
  let elapsed = 0;
  const ok = await waitForJarvis(ORIGIN, {
    timeoutMs: 50, intervalMs: 10, fetchImpl: refused,
    sleep: async (ms) => { elapsed += ms; },
    now: () => elapsed,
  });
  assert.strictEqual(ok, false);
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd electron && node --test test/health.test.js
```

Expected: FAIL — `Cannot find module '../health'`.

- [ ] **Step 3: Implement**

`electron/health.js`:

```javascript
"use strict";

// The contract, verbatim from server.py's /api/health:
//   {"status": "online", "name": "JARVIS", "version": "0.1.0"}
//
// The NAME is what identifies it. "Something answered on 8340" is not the
// same fact, and the difference matters: attaching to a stranger would point
// the window at somebody else's server and, worse, could mean this process
// later decides not to start the one JARVIS actually needs.
const JARVIS_NAME = "JARVIS";

async function probe(origin, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl(`${origin}/api/health`);
  } catch {
    return "nothing";           // refused, unreachable, DNS — nobody home
  }
  if (!response || !response.ok) return "stranger";
  try {
    const body = await response.json();
    return body && body.name === JARVIS_NAME ? "jarvis" : "stranger";
  } catch {
    return "stranger";          // answered, but not with our JSON
  }
}

async function waitForJarvis(origin, {
  timeoutMs = 30000,
  intervalMs = 250,
  fetchImpl = fetch,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  now = () => Date.now(),
} = {}) {
  const started = now();
  for (;;) {
    if (await probe(origin, fetchImpl) === "jarvis") return true;
    if (now() - started >= timeoutMs) return false;
    await sleep(intervalMs);
  }
}

module.exports = { probe, waitForJarvis, JARVIS_NAME };
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd electron && node --test test/health.test.js
```

Expected: 6 passing.

- [ ] **Step 5: Commit**

```bash
git add electron/health.js electron/test/health.test.js
git commit -m "electron: tell a JARVIS from anything else on the port"
```

---

### Task 4: The server's lifecycle — **DONE 2026-09-11**

> **Decided: the flag** (Ken, 2026-09-11). `server.py --ssl/--no-ssl`, with
> `tests/test_ssl_choice.py`; the supervisor spawns `server.py --host <h>
> --port <p> --no-ssl`, both taken from the origin. The committed
> `electron/server.js` is the truth; beyond the code below it also:
>
> - **fails at once when the server exits or cannot spawn** before answering
>   (both hung the code below — watched), and listens for `"error"`, whose
>   unhandled throw would crash Electron's main process;
> - **kills a server it gave up waiting for**, rather than leave it running
>   behind a "failed";
> - **names the likeliest occupant** of an occupied port (a dev JARVIS on
>   HTTPS).
>
> **Measured on Windows, not assumed:** `child.kill()` on the venv's
> `python.exe` — a redirector whose child is the real interpreter — took the
> whole tree (interpreter, brain, the brain's MCP child) and freed the port.
> So did Node exiting WITHOUT calling `stop()`. A run killed mid-flight is
> already failed by `run_store`'s sweep on the next start. macOS: UNVERIFIED.
> End to end with the real supervisor and real servers: nothing on the port
> -> started (825ms) and gone after `stop()`; a JARVIS there -> attached and
> still up after `stop()`; an HTTPS JARVIS -> occupied.
>
> The decision as it was put:
>
> **OPEN DECISION before this task starts (found in Task 3, 2026-09-11).**
> `server.py` switches HTTPS on by itself when `cert.pem` and `key.pem` are
> beside it — measured: a real JARVIS on this box, started with no `--ssl`,
> served TLS. The dev-server workflow requires those certs, so on any
> developer's machine the `spawn(python, ["server.py", "--host",
> "127.0.0.1"])` below starts an HTTPS server, the `http://` health poll never
> sees it, and every launch ends `failed`. Two ways out:
>
> - **A `--no-ssl` flag on `server.py`** (off by default, one argparse line,
>   one pytest), passed by the supervisor. Breaks the "server.py is not
>   modified" constraint, but touches nothing on the voice path.
> - **Spawn `python -m uvicorn server:app` instead**, which does not look for
>   certs, setting `JARVIS_PORT`/`JARVIS_SCHEME`/`JARVIS_BIND_HOST` itself.
>   Keeps the constraint, but duplicates `main()`'s startup — and `main()`'s
>   own comment records a bug from those two entrypoints drifting apart.
>
> Recommended: the flag. Separately, "occupied" is also what a developer's
> own HTTPS JARVIS now reports (Task 3's correction 1), so its `detail` should
> name that likely cause rather than just "not JARVIS".

**Files:**
- Create: `electron/server.js`
- Test: `electron/test/server.test.js`

**Interfaces:**
- Consumes: `findPython` (Task 2), `probe` / `waitForJarvis` (Task 3)
- Produces: `createSupervisor({repoRoot, origin, deps}) => {start(), stop(), startedByUs}`
  where `start()` resolves to `{state: "attached"|"started"|"occupied"|"failed", detail}`.
  Used by Task 5.

- [ ] **Step 1: Write the failing test**

`electron/test/server.test.js`:

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const { createSupervisor } = require("../server");

function deps(overrides = {}) {
  const killed = [];
  return {
    findPython: () => "C:\\repo\\.venv\\Scripts\\python.exe",
    probe: async () => "nothing",
    waitForJarvis: async () => true,
    spawn: () => ({ pid: 4242, kill: (sig) => killed.push(sig), on: () => {} }),
    killed,
    ...overrides,
  };
}

test("attaches to a JARVIS already running, and spawns nothing", async () => {
  let spawned = false;
  const d = deps({ probe: async () => "jarvis", spawn: () => { spawned = true; } });
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "http://127.0.0.1:8340", deps: d });
  const r = await s.start();
  assert.strictEqual(r.state, "attached");
  assert.strictEqual(spawned, false);
  assert.strictEqual(s.startedByUs, false);
});

test("stop() does NOT kill a server it attached to", async () => {
  const d = deps({ probe: async () => "jarvis" });
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "o", deps: d });
  await s.start();
  s.stop();
  assert.deepStrictEqual(d.killed, []);
});

test("spawns when nothing is listening", async () => {
  const d = deps();
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "o", deps: d });
  const r = await s.start();
  assert.strictEqual(r.state, "started");
  assert.strictEqual(s.startedByUs, true);
});

test("stop() kills a server it started", async () => {
  const d = deps();
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "o", deps: d });
  await s.start();
  s.stop();
  assert.strictEqual(d.killed.length, 1);
});

test("refuses a port held by a stranger rather than guessing", async () => {
  let spawned = false;
  const d = deps({ probe: async () => "stranger", spawn: () => { spawned = true; } });
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "o", deps: d });
  const r = await s.start();
  assert.strictEqual(r.state, "occupied");
  assert.strictEqual(spawned, false);
});

test("reports a missing interpreter instead of spawning nothing", async () => {
  const d = deps({ findPython: () => null });
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "o", deps: d });
  const r = await s.start();
  assert.strictEqual(r.state, "failed");
  assert.match(r.detail, /interpreter/i);
});

test("a server that never becomes healthy is a failure, not a hang", async () => {
  const d = deps({ waitForJarvis: async () => false });
  const s = createSupervisor({ repoRoot: "C:\\repo", origin: "o", deps: d });
  const r = await s.start();
  assert.strictEqual(r.state, "failed");
  assert.match(r.detail, /did not answer/i);
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd electron && node --test test/server.test.js
```

Expected: FAIL — `Cannot find module '../server'`.

- [ ] **Step 3: Implement**

`electron/server.js`:

```javascript
"use strict";
const path = require("node:path");

// Every collaborator is injected so the whole lifecycle is testable without
// starting a process or opening a socket. The tests below are the reason the
// hard part of this application has no Electron in it.
function createSupervisor({ repoRoot, origin, deps = {} }) {
  const {
    findPython = require("./python").findPython,
    probe = require("./health").probe,
    waitForJarvis = require("./health").waitForJarvis,
    spawn = require("node:child_process").spawn,
    log = () => {},
  } = deps;

  let child = null;
  let startedByUs = false;

  async function start() {
    const found = await probe(origin);

    if (found === "jarvis") {
      // Attach. Never start a second: two servers means two brains on one
      // Claude subscription and two writers on one SQLite database, and
      // run_store is not built for that — the second would be quietly wrong.
      log(`attaching to the JARVIS already serving ${origin}`);
      startedByUs = false;
      return { state: "attached", detail: origin };
    }

    if (found === "stranger") {
      // Refuse rather than guess. Something is on the port and it is not us.
      return {
        state: "occupied",
        detail: `Something is already using ${origin}, and it is not JARVIS.`,
      };
    }

    const python = findPython(repoRoot);
    if (!python) {
      return {
        state: "failed",
        detail: `No Python interpreter found. Expected a venv at ` +
                `${path.join(repoRoot, ".venv")}.`,
      };
    }

    log(`starting ${python} server.py`);
    child = spawn(python, ["server.py", "--host", "127.0.0.1"], {
      cwd: repoRoot,
      stdio: "inherit",
    });
    startedByUs = true;

    if (!(await waitForJarvis(origin))) {
      return {
        state: "failed",
        detail: `The server was started but did not answer on ${origin}.`,
      };
    }
    return { state: "started", detail: origin };
  }

  function stop() {
    // The one boolean that must never be guessed at. Killing a server this
    // process attached to would take down somebody's dev server on exit.
    if (!startedByUs || !child) return;
    try {
      child.kill();
    } catch {
      // already gone
    }
    child = null;
  }

  return {
    start,
    stop,
    get startedByUs() { return startedByUs; },
  };
}

module.exports = { createSupervisor };
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd electron && node --test test/server.test.js
```

Expected: 7 passing.

- [ ] **Step 5: Commit**

```bash
git add electron/server.js electron/test/server.test.js
git commit -m "electron: attach, spawn, and kill only what we started"
```

---

### Task 5: The window, and the permission handler

**Files:**
- Create: `electron/main.js`
- Create: `electron/preload.js`

**Interfaces:**
- Consumes: `createSupervisor` (Task 4)
- Produces: a launchable application. Task 6 adds the tray to this file.

- [ ] **Step 1: Write the preload**

`electron/preload.js`:

```javascript
// Deliberately empty of privilege. The renderer is the ordinary JARVIS page
// served over HTTP; it needs nothing from Node, and `contextIsolation` stays
// on. This file exists so that adding something later is a change to a file
// that is already wired up rather than a change to the security model.
```

- [ ] **Step 2: Write the main process**

`electron/main.js`:

```javascript
"use strict";
const { app, BrowserWindow, dialog, session, systemPreferences } = require("electron");
const path = require("node:path");
const { createSupervisor } = require("./server");

const ORIGIN = process.env.JARVIS_ORIGIN || "http://127.0.0.1:8340";
const REPO_ROOT = path.resolve(__dirname, "..");

let win = null;
const supervisor = createSupervisor({
  repoRoot: REPO_ROOT,
  origin: ORIGIN,
  deps: { log: (m) => console.log(`[jarvis] ${m}`) },
});

// HTTP and not HTTPS, deliberately. The certificates exist for one reason —
// frontend/vite.config.ts hard-codes an HTTPS proxy target — and there is no
// Vite here. `http://127.0.0.1` is a secure context by the same rule that
// makes localhost one, so getUserMedia works and the openssl step disappears
// from this path. It does NOT disappear from the dev-server workflow.

async function grantMicrophone() {
  // Measured in 4-zero: Electron DENIES media unless this handler exists, and
  // the resulting failure is indistinguishable from the macOS TCC case below.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, cb) => {
    cb(permission === "media" || permission === "audioCapture");
  });

  // macOS only, and UNVERIFIED — written from documentation on a Windows box,
  // which is the condition that cost this port two wrong premises. TCC is a
  // SECOND gate the handler above does not satisfy; a packaged build also
  // needs NSMicrophoneUsageDescription in its Info.plist. Install the handler,
  // still fail, and there is no way to tell which gate is shut.
  if (process.platform === "darwin") {
    try {
      const status = systemPreferences.getMediaAccessStatus("microphone");
      console.log(`[jarvis] macOS microphone TCC status: ${status}`);
      if (status !== "granted") {
        const ok = await systemPreferences.askForMediaAccess("microphone");
        console.log(`[jarvis] askForMediaAccess -> ${ok}`);
      }
    } catch (e) {
      console.log(`[jarvis] TCC probe failed: ${e.message}`);
    }
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
  win.loadURL(ORIGIN);
  return win;
}

app.on("ready", async () => {
  await grantMicrophone();

  const result = await supervisor.start();
  console.log(`[jarvis] server: ${result.state} — ${result.detail}`);

  if (result.state === "occupied" || result.state === "failed") {
    dialog.showErrorBox("JARVIS could not start", result.detail);
    app.quit();
    return;
  }
  createWindow();
});

// Task 6 replaces this with tray behaviour. Until then, closing quits.
app.on("window-all-closed", () => app.quit());

app.on("before-quit", () => supervisor.stop());
```

- [ ] **Step 3: Install Electron and launch it**

```bash
cd electron && npm install
node node_modules/electron/install.js
npm start
```

Expected: the console prints `server: started` or `server: attached`, and a
window opens showing the JARVIS orb.

- [ ] **Step 4: Confirm both branches by hand**

With no server running, `npm start` should print `server: started` and spawn
one. With a server already running, it should print `server: attached` — and
after quitting the app, **that server must still be running**.

```bash
curl -s -o /dev/null -w "server still up after quit: %{http_code}\n" http://127.0.0.1:8340/api/health
```

Expected: `200`.

- [ ] **Step 5: Commit**

```bash
git add electron/main.js electron/preload.js
git commit -m "electron: a window, a supervised server, and a microphone"
```

---

### Task 6: The tray, and what quit means

**Files:**
- Modify: `electron/main.js`
- Create: `electron/tray-icon.png` (a 32x32 PNG; any placeholder mark is fine
  for this task — it is replaced when the app gets an identity)

**Interfaces:**
- Consumes: the window and supervisor from Task 5
- Produces: tray-resident lifecycle. No later task depends on it.

- [ ] **Step 1: Replace the close-quits behaviour**

In `electron/main.js`, add `Tray` and `Menu` to the `electron` require, then
add above `app.on("ready")`:

```javascript
let tray = null;
// The one flag that separates "the user closed the window" from "the user
// asked to quit". Without it, `before-quit` cannot tell whether hiding or
// exiting was meant, and the app either cannot be closed or cannot be quit.
let reallyQuitting = false;

function createTray() {
  const { Tray, Menu } = require("electron");
  tray = new Tray(path.join(__dirname, "tray-icon.png"));
  tray.setToolTip("JARVIS");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Show JARVIS", click: () => { if (win) { win.show(); win.focus(); } } },
    { type: "separator" },
    // Quit must be findable. An application a person cannot work out how to
    // exit is worse than one that simply closes when you close it.
    { label: "Quit JARVIS", click: () => { reallyQuitting = true; app.quit(); } },
  ]));
  tray.on("double-click", () => { if (win) { win.show(); win.focus(); } });
}
```

- [ ] **Step 2: Make closing hide**

Inside `createWindow()`, after `win.loadURL(ORIGIN)`:

```javascript
  // Closing HIDES. The server keeps running and JARVIS keeps listening —
  // which is the whole point of tray residency, and is only sound because
  // Task 1 measured that audio survives a hidden window.
  win.on("close", (event) => {
    if (reallyQuitting) return;
    event.preventDefault();
    win.hide();
  });
```

- [ ] **Step 3: Stop the app quitting when the window closes**

Replace:

```javascript
app.on("window-all-closed", () => app.quit());
```

with:

```javascript
// Deliberately does nothing. Closing the window hides it; the application
// exits only through the tray's Quit, which sets `reallyQuitting`.
app.on("window-all-closed", () => {});
```

and call `createTray();` immediately after `createWindow();` in the ready
handler.

- [ ] **Step 4: Exercise it by hand**

Launch with `npm start`. Then:

1. Close the window — the app must stay running and the tray icon remain.
2. Double-click the tray icon — the window must come back.
3. Speak while the window is closed, then reopen it — the conversation must
   show that JARVIS heard you.
4. Tray menu -> Quit JARVIS — the app must exit, and the server with it if
   this process started it.

- [ ] **Step 5: Commit**

```bash
git add electron/main.js electron/tray-icon.png
git commit -m "electron: closing hides, the tray quits"
```

---

### Task 7: Saying so when the backend is deaf

**Files:**
- Modify: `electron/main.js`
- Create: `electron/backend.js`
- Test: `electron/test/backend.test.js`

**Interfaces:**
- Consumes: `ORIGIN` from Task 5
- Produces: `sttWarning(status: object) => string | null`

- [ ] **Step 1: Write the failing test**

`electron/test/backend.test.js`:

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const { sttWarning } = require("../backend");

test("warns when the browser backend is configured", () => {
  const w = sttWarning({ stt_backend: "browser" });
  assert.ok(w && /whisper/i.test(w), w);
});

test("says nothing when a local backend is configured", () => {
  assert.strictEqual(sttWarning({ stt_backend: "whisper" }), null);
});

test("says nothing rather than guessing when the status is unreadable", () => {
  assert.strictEqual(sttWarning(null), null);
  assert.strictEqual(sttWarning({}), null);
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd electron && node --test test/backend.test.js
```

Expected: FAIL — `Cannot find module '../backend'`.

- [ ] **Step 3: Implement**

`electron/backend.js`:

```javascript
"use strict";

// Electron has no speech service. Measured in 4-zero: webkitSpeechRecognition
// is DEFINED there and fails at runtime with error=network, so a browser
// backend under Electron looks alive and never returns a word.
//
// This reports; it does not fix. Rewriting the user's .env to suit the
// application is worse than explaining what is wrong — a program that edits
// configuration behind you is harder to trust than one that is inconvenient.
function sttWarning(status) {
  if (!status || typeof status.stt_backend !== "string") return null;
  if (status.stt_backend !== "browser") return null;
  return (
    "JARVIS is set to use the browser's speech recogniser, and Electron has " +
    "no speech service behind it — nothing will be transcribed.\n\n" +
    "Install the local backend and set JARVIS_STT_BACKEND=whisper in .env:\n" +
    "    pip install -r requirements-stt.txt"
  );
}

module.exports = { sttWarning };
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd electron && node --test test/backend.test.js
```

Expected: 3 passing.

- [ ] **Step 5: Show it after the window opens**

In `electron/main.js`, add to the require block:

```javascript
const { sttWarning } = require("./backend");
```

and at the end of the `app.on("ready")` handler, after `createTray();`:

```javascript
  // After the window, not before: a warning in front of a blank screen reads
  // like a crash, and this is information rather than a failure to start.
  try {
    const status = await (await fetch(`${ORIGIN}/api/settings/status`)).json();
    const warning = sttWarning(status);
    if (warning) dialog.showMessageBox(win, { type: "warning", title: "JARVIS cannot hear", message: warning });
  } catch (e) {
    console.log(`[jarvis] could not read settings status: ${e.message}`);
  }
```

- [ ] **Step 6: Commit**

```bash
git add electron/backend.js electron/test/backend.test.js electron/main.js
git commit -m "electron: say so when the configured recogniser cannot work here"
```

---

### Task 8: Run it, and write down what happened

**This task is the deliverable, not a formality.** Phase 4c shipped with "the
page half has never been run against a live JARVIS" written into its own
commit message; ten minutes of running it produced four defects, two of which
no test could reach. Phase 5 is not done until somebody has used it.

**Files:**
- Modify: `docs/plans/phase-5-electron.md`
- Modify: `CLAUDE.md`
- Modify: `docs/plans/cross-platform-port.md`

**Interfaces:**
- Consumes: everything above
- Produces: nothing further

- [ ] **Step 1: Run the whole thing and talk to it**

```bash
cd electron && npm start
```

Do all of this, in order, and note what happens at each point:

1. Speak a command with a project name in it — does it act?
2. Talk over JARVIS while he replies — does barge-in work in Electron?
3. Close the window. Speak. Reopen — was it heard?
4. Tray -> Quit. Is the server gone?
5. Start a server yourself, then `npm start` — does it attach? After quitting
   the app, is your server still running?

- [ ] **Step 2: Run both gates**

```bash
cd electron && npm test
cd .. && .venv/Scripts/python -m pytest -q
```

Expected: all Electron tests pass; the Python suite is unchanged by this phase
and must still be green.

- [ ] **Step 3: Record what the run found**

Add a "What running it found" section to
`docs/plans/phase-5-electron.md` — including anything that did NOT work.
A phase that reports only successes is the one nobody trusts later.

- [ ] **Step 4: Update the standing documentation**

In `CLAUDE.md`, add `electron/` to the Key Files list:

```markdown
- `electron/` — the desktop application: a tray-resident Electron shell that
  starts and supervises `server.py`, and loads the page the server itself
  serves. The supervision logic (`server.js`, `health.js`, `python.js`) has no
  Electron import and is tested with `node --test`; `main.js` is the only file
  that touches Electron. It attaches to a server that is already running and
  kills one only if it started it
```

In `docs/plans/cross-platform-port.md`, mark phase 5 done in the table.

- [ ] **Step 5: Commit**

```bash
git add docs/plans/phase-5-electron.md docs/plans/cross-platform-port.md CLAUDE.md
git commit -m "Phase 5: what running the Electron application found"
```

---

## Self-review

**Spec coverage.** Every section of `phase-5-electron.md` has a task: the
renderer loading the server's page (5), HTTP rather than HTTPS (5), the server
lifecycle table (4), Python discovery (2), the tray (6), permissions including
the unverified macOS half (5), the STT backend warning (7), testing (2/3/4 and
8), and the hidden-window risk the spec flagged as "do it first" (1).

**Placeholders.** None. Every code step carries the code; the only deliberately
empty file is `preload.js`, and its emptiness is the point and is explained in
the file.

**Type consistency.** `findPython(repoRoot) => string|null` is produced in
Task 2 and consumed in Task 4. `probe(origin, fetchImpl) => "jarvis" |
"stranger" | "nothing"` and `waitForJarvis(origin, opts) => boolean` are
produced in Task 3 and consumed in Task 4. `createSupervisor(...)` returning
`{start, stop, startedByUs}` with `start()` resolving to
`{state, detail}` is produced in Task 4 and consumed in Task 5.
`sttWarning(status) => string|null` is produced and consumed in Task 7. The
`state` values `"attached" | "started" | "occupied" | "failed"` are used
identically in Tasks 4 and 5.

**One risk this plan cannot remove.** Task 1 can invalidate Tasks 6 and 8. It
is first for that reason, and it says explicitly to stop rather than continue
if the answer comes back wrong.
