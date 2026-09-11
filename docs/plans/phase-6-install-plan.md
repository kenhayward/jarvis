# Phase 6: install.py — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command, `install.py`, turns a git checkout of JARVIS into a
working desktop application on Ken's own machines — and brings it up to date
after every `git pull` — plus a "Start with Windows" tray checkbox.

**Architecture:** `install.py` at the repository root, standard library only,
is a list of steps run in order; each checks before it acts, stamps what it
built, and raises `StepFailed` to stop the run. Every program it starts goes
through one function, `run`, which the tests replace, so the whole script is
tested without installing anything. The `.env` parser moves into
`env_file.py` so the script and the server share one definition. The Electron
side gains `electron/login.js` (pure, `node:test`-tested) and a checkbox in
`main.js`.

**Tech Stack:** Python 3.11+ standard library; pytest; Node 22.12+,
`node:test`; Electron 44; PowerShell (`WScript.Shell`) for the shortcut.

**Spec:** [`docs/plans/phase-6-install.md`](phase-6-install.md)

> **Where this file lives.** The writing-plans skill's default is
> `docs/superpowers/plans/`. `CLAUDE.md` forbids re-adding that directory, so
> this sits in `docs/plans/` with every other planning document.

## Global Constraints

- **`install.py` and `env_file.py` import the standard library only.** They
  run before the venv they create exists. Task 3 pins this with a test.
- **Python 3.11 or newer; Node 22.12.0 or newer** (Electron 44's `engines`).
- **Prerequisites are checked, never installed.** Hints name the package
  manager the machine HAS (`winget`, `brew`), never its OS name.
- **Every program is run by the full path `which` found**, never a bare name.
  On Windows `npm` is `npm.cmd`; CreateProcess cannot find a bare `npm`.
- **The first failing step stops the run**, printing the command and the end
  of its output.
- **An existing `.env` is never modified.** Only a missing one is created.
- **Paths reach PowerShell only through environment variables**, never
  spliced into script text.
- **"Start with Windows" is off by default and exists only on Windows.**
- **macOS behaviour is marked UNVERIFIED** in code and docs until Ken runs it
  on the Mac.
- **Files containing backslashes are written with the Write/Edit tools, never
  a shell heredoc** — in this environment a heredoc collapses `\\` to `\`,
  silently (it put a carriage return in phase 5's test paths).
- Branch `feat/phase-6-install` off `main`; commit per task; push and PR only
  when Ken asks. PRs: `gh pr create --repo kenhayward/jarvis --base main`.
- Gates: `.venv/Scripts/python -m pytest` (bare, whole suite) and
  `cd electron && npm test`.

## File structure

| file | responsibility |
|---|---|
| `env_file.py` (new) | the one definition of a `.env` line — moved from `server.py` |
| `server.py` | imports `_parse_env_lines` from `env_file` instead of defining it |
| `install.py` (new) | the steps, the runner seam, `main()` |
| `tests/test_install.py` (new) | every step's decisions, with `run`/`which` faked |
| `tests/test_env_file.py` (new) | the one-definition pin |
| `electron/jarvis.ico` (new) | the Start-menu icon |
| `electron/login.js` (new) | the login-item decisions, no Electron import |
| `electron/test/login.test.js` (new) | its tests |
| `electron/main.js` | the checkbox and the `--hidden` launch |
| `.github/workflows/tests.yml` | runs `cd electron && npm test` |
| `CLAUDE.md`, `docs/plans/*.md` | the Quick Start, the phase record |

---

### Task 1: Does a window that was never shown capture audio? — **DONE 2026-09-11**

> **Answered: yes.** Never shown, no gesture: 99.9% over five minutes against
> a shown control's 99.9%, and 99.8% on a one-minute check during which the
> window was confirmed absent from the desktop. Both audio contexts ran
> without a click. Task 10 keeps `show: false` at login; no fallback. Full
> record in `phase-6-install.md`.

**This task comes first because it can change Task 10.** Phase 5 measured a
window shown and then hidden. Started at login, the window is never shown at
all — a different state. Chromium may not run capture there, and the page's
audio contexts may stay suspended without the click `main.ts` resumes them on
(`frontend/src/main.ts:266-274`).

The output is an **answer**. Everything built here is throwaway, under the
ignored `.agents/`, and deleted at the end.

**Files:**
- Create (throwaway): `.agents/spikes/never-shown/` — ignored by git

**Interfaces:**
- Consumes: nothing
- Produces: a recorded finding in `docs/plans/phase-6-install.md`, and a
  verdict Task 10 follows

- [ ] **Step 1: Make sure nothing else is listening**

Phase 5's lesson: a JARVIS page left open held the same microphone and made a
result look like evidence against the true cause. Quit any JARVIS (tray ->
Quit), close any JARVIS browser tab, and check the ports are free:

```bash
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8340,8341,5173 -State Listen -ErrorAction SilentlyContinue"
```

Expected: no output.

- [ ] **Step 2: Write the spike**

Use the Write tool. `.agents/spikes/never-shown/package.json`:

```json
{ "name": "never-shown-spike", "private": true, "main": "main.js" }
```

`.agents/spikes/never-shown/main.js`:

```javascript
// THROWAWAY. Does a window that is NEVER shown capture audio, and do its
// audio contexts run without a user gesture? SPIKE_MODE=shown is the control.
const { app, BrowserWindow, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const MODE = process.env.SPIKE_MODE || "never-shown";
const MINUTES = Number(process.env.SPIKE_MINUTES || 5);
const out = path.join(__dirname, `result-${MODE}.log`);
fs.writeFileSync(out, "");
const log = (m) => { console.log(m); fs.appendFileSync(out, m + "\n"); };

app.on("ready", () => {
  session.defaultSession.setPermissionRequestHandler((_wc, permission, cb, details) => {
    log(`[main] permission ${permission} ${JSON.stringify(details && details.mediaTypes)} -> granted`);
    cb(true);
  });
  const win = new BrowserWindow({
    width: 600, height: 400, show: MODE === "shown",
    webPreferences: { backgroundThrottling: false },    // as main.js has it
  });
  win.webContents.on("console-message", (_e, _level, message) => log(message));
  win.loadFile(path.join(__dirname, "probe.html"));
  log(`[main] mode=${MODE} visible=${win.isVisible()} minutes=${MINUTES}`);
  setTimeout(() => { log("[main] done"); app.quit(); }, MINUTES * 60 * 1000 + 3000);
});
```

`.agents/spikes/never-shown/probe.html`:

```html
<!doctype html><meta charset="utf-8"><title>never-shown spike</title>
<script src="probe.js"></script>
```

`.agents/spikes/never-shown/probe.js`:

```javascript
// Mirrors the page: capture starts on its own a second after load, with NO
// user gesture, through a 16 kHz AudioContext and a ScriptProcessorNode
// (frontend/src/capture.ts). A second context stands in for playback.
setTimeout(async () => {
  const playback = new AudioContext();
  console.log(`[page] visibility=${document.visibilityState} playback.state=${playback.state}`);
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext({ sampleRate: 16000 });
  console.log(`[page] capture.state=${ctx.state} (no gesture)`);
  const src = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  let samples = 0;
  node.onaudioprocess = (e) => { samples += e.inputBuffer.length; };
  src.connect(node);
  node.connect(ctx.destination);
  const started = performance.now();
  setInterval(() => {
    const secs = (performance.now() - started) / 1000;
    const pct = (100 * samples / (secs * 16000)).toFixed(1);
    console.log(`[page] t=${secs.toFixed(0)}s samples=${samples} of ${Math.round(secs * 16000)} = ${pct}% ` +
                `capture.state=${ctx.state} playback.state=${playback.state} visibility=${document.visibilityState}`);
  }, 10000);
}, 1000);
```

- [ ] **Step 3: Install Electron into the spike**

```bash
cd .agents/spikes/never-shown && npm install electron@44.3.0 --no-save && node node_modules/electron/install.js
```

Expected: `node_modules/electron/dist/electron.exe` exists (from the cache
phase 5 filled; no fresh download).

- [ ] **Step 4: Run the control, then the case**

Five minutes each, back to back, nothing else holding the microphone:

```bash
cd .agents/spikes/never-shown && SPIKE_MODE=shown node_modules/electron/dist/electron.exe .
cd .agents/spikes/never-shown && SPIKE_MODE=never-shown node_modules/electron/dist/electron.exe .
```

Read `result-shown.log` and `result-never-shown.log`.

Expected if the design holds: the never-shown run reports `visible=false`,
the permission granted, `capture.state=running` and `playback.state=running`
with no gesture, and a final percentage comparable to phase 5's fixed hidden
window (95.7%) against a control near 100%.

- [ ] **Step 5: Record the finding in the spec, and the verdict**

Add a section to `docs/plans/phase-6-install.md` before "What would make this
design wrong": both runs' final lines, the context states, and the verdict.
Strike through that section's first bullet and point to the finding.

**If the never-shown run captures nothing, or either context stays
`suspended`:** Task 10 takes the fallback the spec names — at login the
window is created shown and hidden again as soon as the page has loaded, so
capture begins in a window that has been shown (phase 5's measured case).
Write that into Task 10's Step 5 before starting it.

- [ ] **Step 6: Delete the spike and commit**

```bash
rm -rf .agents/spikes/never-shown
git add docs/plans/phase-6-install.md
git commit -m "Phase 6 spike: whether a never-shown window captures audio"
```

---

### Task 2: One definition of a `.env` line, importable without the venv — **DONE 2026-09-11** (`cf77e06`)

**Files:**
- Create: `env_file.py`
- Modify: `server.py:27-47` (the `_parse_env_lines` definition and its comment)
- Test: `tests/test_env_file.py`

**Interfaces:**
- Consumes: nothing
- Produces: `env_file.parse_env_lines(text: str) -> list[tuple[str, str]]`;
  `server._parse_env_lines` is that same function object. Used by Task 5.

- [ ] **Step 1: Write the failing test**

`tests/test_env_file.py`:

```python
"""The one definition of a line of `.env`.

It lived in server.py, and install.py cannot import server.py -- whose
imports need the venv install.py has not built yet. So it moved to a module
of its own, and this pins that it moved rather than being copied: three
copies once disagreed, and the gap let a POSTed value redirect the binary
the brain is spawned from (see env_file.py).
"""
import env_file
import server


def test_the_server_uses_the_one_definition_not_a_copy():
    assert server._parse_env_lines is env_file.parse_env_lines


def test_it_still_reads_a_line_the_way_the_server_always_has():
    text = '# a comment\nA=1\n  B = "two" \nC=\'three\'\nnot a line\n'
    assert env_file.parse_env_lines(text) == [("A", "1"), ("B", "two"), ("C", "three")]


def test_every_line_separator_python_knows_is_a_line_separator():
    # The reason it is one function: splitlines() splits on ten characters,
    # and a writer that forbade only three let a value smuggle in a line.
    assert env_file.parse_env_lines("A=1\x0bB=2") == [("A", "1"), ("B", "2")]
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/Scripts/python -m pytest tests/test_env_file.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'env_file'`.

- [ ] **Step 3: Move the function**

Create `env_file.py` (Write tool):

```python
"""The ONE definition of what a line of `.env` is.

Standard library only: install.py reads `.env` with it before the venv
exists, and must read it exactly as the server does.

Every reader uses it -- server.py's boot loader and `_read_env`, and
`_env_value_problem`, which is what the settings writer asks before it puts
a value on a line. One function rather than three copies because the copies
disagreed. The writer forbade three characters -- "\\n", "\\r", "\\0" -- and
`str.splitlines()` splits on ten, so `{"user_name": "Tony\\x0bJARVIS_CLAUDE_PATH=/tmp/evil"}`
came back 200 and `_read_env()` then reported JARVIS_CLAUDE_PATH=/tmp/evil.
That is the binary the brain is spawned from, and /api/restart is one call
away. Extending the blocklist to ten characters would have left the same
shape of bug for the next separator; deriving the writer's rule from the
reader's parser cannot.
"""


def parse_env_lines(text: str) -> list[tuple[str, str]]:
    """Every (key, value) a reader of `.env` sees in `text`, in order."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out.append((k.strip(), v.strip().strip('"').strip("'")))
    return out
```

In `server.py`, replace the whole block from `# The ONE definition of what a
line of \`.env\` is.` through the end of `def _parse_env_lines` (lines 27-47)
with (Edit tool):

```python
# The ONE definition of what a line of `.env` is lives in env_file.py -- see
# its docstring for why there is exactly one. Imported under the old name so
# every reader in this file, and every test, is unchanged.
from env_file import parse_env_lines as _parse_env_lines
```

- [ ] **Step 4: Run the tests and watch them pass**

The new file, plus every existing test that reaches the parser (found with
`grep -rln "_parse_env_lines\|_env_value_problem\|_read_env" tests/`):

```bash
.venv/Scripts/python -m pytest tests/test_env_file.py tests/test_env_lines.py tests/test_anchored_patterns.py tests/test_bounds.py tests/test_no_anthropic_sdk.py tests/test_voice_settings.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add env_file.py server.py tests/test_env_file.py
git commit -m "env_file: the one .env parser, importable without the venv"
```

---

### Task 3: `install.py`'s spine, and the prerequisites — **DONE 2026-09-11**

> Run for real on the Windows box: `Python 3.14.6, node v24.16.0`, with
> `npm` found as `C:\Program Files\nodejs\npm.CMD` — the case the full-path
> rule exists for. **Note for Task 12:** `py` here is 3.14, so a fresh
> clone's venv will be 3.14, not the existing checkout's 3.13. If
> CTranslate2 (faster-whisper) or onnxruntime (piper) publish no 3.14
> wheels, pip fails there — and the answer is a Python version floor or
> ceiling, measured, not guessed.

**Files:**
- Create: `install.py`
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: nothing
- Produces (all in `install.py`, used by every later task):
  - `class StepFailed(Exception)` with `.message: str`, `.command: list[str] | None`, `.output: str`
  - `@dataclass Result(returncode: int, stdout: str, stderr: str)` with property `output -> str`
  - `run(argv: list, *, cwd: Path | None = None, env: dict | None = None) -> Result`
  - `which(name: str) -> str | None`
  - `must(result: Result, argv: list, what: str) -> Result`
  - `@dataclass Context(root: Path, env: dict[str, str], python: str, version: tuple, tools: dict[str, str])`
  - `prerequisites(ctx: Context) -> str` — fills `ctx.tools` with full paths for `node`, `npm`, and when present `git`, `claude`
  - `MIN_PYTHON = (3, 11)`, `MIN_NODE = (22, 12, 0)`, `STAMP = ".jarvis-install-stamp"`
  - every step is `def step(ctx: Context) -> str` (the status to print) and raises `StepFailed`

- [ ] **Step 1: Write the failing tests**

`tests/test_install.py` (Write tool):

```python
"""install.py: every step's decision, with nothing actually installed.

`install.run` is the one place the script starts a program and `install.which`
the one place it looks one up; the fixtures replace both, so these tests run
on either CI platform without pip, npm, PowerShell or a network.
"""
import ast
import sys
from pathlib import Path

import pytest

import install


class Recorder:
    """Stands in for `install.run`: records every call, answers by rule.

    `reply(match, result, effect=None)`: the first rule whose `match(argv)` is
    true answers. `result` may be a list, consumed one per call (the last one
    repeats); `effect(argv, cwd, env)` runs first, to create the files a real
    command would have left behind.
    """

    def __init__(self):
        self.calls = []
        self._rules = []

    def reply(self, match, result, effect=None):
        results = list(result) if isinstance(result, list) else [result]
        self._rules.append((match, results, effect))

    def __call__(self, argv, *, cwd=None, env=None):
        argv = [str(a) for a in argv]
        self.calls.append({"argv": argv, "cwd": cwd, "env": env})
        for match, results, effect in self._rules:
            if match(argv):
                if effect:
                    effect(argv, cwd, env)
                return results.pop(0) if len(results) > 1 else results[0]
        return install.Result(0, "", "")

    def argvs(self):
        return [c["argv"] for c in self.calls]


def ok(stdout=""):
    return install.Result(0, stdout, "")


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(install, "run", r)
    return r


@pytest.fixture
def tools(monkeypatch):
    """What `which` finds. Deliberately Windows-shaped: npm is npm.cmd."""
    found = {"node": "/fake/bin/node", "npm": "/fake/bin/npm.cmd",
             "git": "/fake/bin/git", "claude": "/fake/bin/claude"}
    monkeypatch.setattr(install, "which", lambda name: found.get(name))
    return found


def make_ctx(root, **kw):
    kw.setdefault("env", {})
    kw.setdefault("version", (3, 13, 0))
    kw.setdefault("python", "/fake/python3")
    return install.Context(root=root, **kw)


def node_says(version):
    return lambda argv: argv[-1] == "--version", ok(version)


# --- the spine ------------------------------------------------------------

def test_install_py_needs_nothing_but_the_standard_library():
    """It runs before the venv it creates exists."""
    for name in ("install.py", "env_file.py"):
        tree = ast.parse((Path(install.__file__).parent / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module]
            else:
                continue
            for mod in mods:
                top = mod.split(".")[0]
                assert top in sys.stdlib_module_names or top in ("env_file", "__future__"), \
                    f"{name} imports {mod}, which the fresh machine will not have"


def test_run_keeps_stdout_apart_from_stderr():
    r = install.run([sys.executable, "-c",
                     "import sys; print('out'); print('err', file=sys.stderr)"])
    assert r.returncode == 0 and r.stdout.strip() == "out"
    assert "out" in r.output and "err" in r.output


def test_must_turns_a_failed_command_into_a_stop_that_carries_it():
    with pytest.raises(install.StepFailed) as e:
        install.must(install.Result(2, "", "boom"), ["/x/tool", "arg"], "tool failed")
    assert e.value.command == ["/x/tool", "arg"] and "boom" in e.value.output


# --- prerequisites -----------------------------------------------------------

def test_an_old_python_stops_before_anything_is_touched(tmp_path, rec, tools):
    with pytest.raises(install.StepFailed, match="3.11"):
        install.prerequisites(make_ctx(tmp_path, version=(3, 10, 9)))
    assert rec.calls == []


def test_a_missing_node_stops_with_a_hint(tmp_path, rec, tools):
    del tools["node"]
    with pytest.raises(install.StepFailed, match="Node 22.12"):
        install.prerequisites(make_ctx(tmp_path))


def test_node_older_than_electrons_floor_is_refused(tmp_path, rec, tools):
    rec.reply(*node_says("v22.11.0\n"))
    with pytest.raises(install.StepFailed, match="22.12"):
        install.prerequisites(make_ctx(tmp_path))


def test_programs_are_run_by_the_path_which_found(tmp_path, rec, tools):
    """On Windows npm is npm.cmd, and CreateProcess cannot find a bare `npm`:
    the extension bug this port has met three times. So nothing is ever run
    by its bare name."""
    rec.reply(*node_says("v24.16.0\n"))
    ctx = make_ctx(tmp_path)
    install.prerequisites(ctx)
    assert rec.argvs() == [[tools["node"], "--version"]]
    assert ctx.tools["npm"] == tools["npm"] and ctx.tools["node"] == tools["node"]


def test_no_claude_or_git_is_a_note_not_a_stop(tmp_path, rec, tools):
    del tools["claude"], tools["git"]
    rec.reply(*node_says("v24.16.0\n"))
    status = install.prerequisites(make_ctx(tmp_path))
    assert "no `claude`" in status and "@anthropic-ai/claude-code" in status
    assert "no `git`" in status


def test_the_hint_follows_the_package_manager_the_machine_has(monkeypatch):
    monkeypatch.setattr(install, "which", lambda n: "/x/winget" if n == "winget" else None)
    assert install._install_hint("node") == "winget install OpenJS.NodeJS.LTS"
    monkeypatch.setattr(install, "which", lambda n: "/x/brew" if n == "brew" else None)
    assert install._install_hint("node") == "brew install node"
    monkeypatch.setattr(install, "which", lambda n: None)
    assert "PATH" in install._install_hint("node")
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/Scripts/python -m pytest tests/test_install.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'install'`.

- [ ] **Step 3: Write the spine and the first step**

`install.py` (Write tool):

```python
"""Set up JARVIS from this git checkout, or bring a set-up checkout up to date.

    py install.py          Windows
    python3 install.py     macOS (UNVERIFIED until run on the Mac)

Run it again after every `git pull`: each step checks before it acts, so a run
with nothing to do takes seconds. The design is docs/plans/phase-6-install.md.

Standard library only -- this runs before the venv it creates exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent
MIN_PYTHON = (3, 11)
# Electron 44's own floor -- its package.json `engines`, and its downloader's.
# Vite accepts older, so Electron is what sets it.
MIN_NODE = (22, 12, 0)
STAMP = ".jarvis-install-stamp"


class StepFailed(Exception):
    """A step that could not finish. The run stops here: carrying on past a
    failure leaves a checkout that looks installed and is not."""

    def __init__(self, message: str, command: list[str] | None = None, output: str = ""):
        super().__init__(message)
        self.message = message
        self.command = command
        self.output = output


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def run(argv: list, *, cwd: Path | None = None, env: dict | None = None) -> Result:
    """The ONE place this script starts a program. The tests replace it.

    `argv[0]` is always a full path from `which`, never a bare name: on
    Windows `npm` is `npm.cmd`, and CreateProcess will not find a bare `npm`.
    """
    proc = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return Result(proc.returncode, proc.stdout or "", proc.stderr or "")


def which(name: str) -> str | None:
    """The ONE place this script looks a program up. The tests replace it."""
    return shutil.which(name)


def must(result: Result, argv: list, what: str) -> Result:
    if result.returncode != 0:
        raise StepFailed(what, [str(a) for a in argv], result.output)
    return result


@dataclass
class Context:
    root: Path
    env: dict[str, str]
    python: str = sys.executable
    version: tuple = tuple(sys.version_info[:3])
    tools: dict[str, str] = field(default_factory=dict)


def _version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _install_hint(what: str) -> str:
    """How to get `what` here -- by the package manager this machine HAS,
    not by the name of its operating system."""
    if what == "claude":
        return "npm install -g @anthropic-ai/claude-code, then run `claude` once to log in"
    if which("winget"):
        return {"python": "winget install Python.Python.3.13",
                "node": "winget install OpenJS.NodeJS.LTS",
                "git": "winget install Git.Git"}[what]
    if which("brew"):
        return {"python": "brew install python@3.13",
                "node": "brew install node",
                "git": "brew install git"}[what]
    return f"install {what} and make sure it is on PATH"


def prerequisites(ctx: Context) -> str:
    """Checked, never installed. Python, Node and npm stop the run; git and
    claude are notes, because nothing this script installs needs them -- git
    is for the next `git pull`, and preflight judges Claude Code at the end."""
    if tuple(ctx.version[:2]) < MIN_PYTHON:
        raise StepFailed(
            f"this is Python {ctx.version[0]}.{ctx.version[1]}; JARVIS needs 3.11 or "
            f"newer. Get one ({_install_hint('python')}) and run install.py with it.")
    for name in ("node", "npm"):
        found = which(name)
        if not found:
            raise StepFailed(f"no `{name}` on PATH. JARVIS needs Node 22.12 or newer: "
                             f"{_install_hint('node')}")
        ctx.tools[name] = found
    argv = [ctx.tools["node"], "--version"]
    said = must(run(argv), argv, "node would not report its version").stdout.strip()
    got = _version(said)
    if got is None or got < MIN_NODE:
        raise StepFailed(f"node is {said or 'unknown'}; Electron 44 needs 22.12 or newer. "
                         f"{_install_hint('node')}")
    lines = [f"Python {'.'.join(map(str, ctx.version))}, node {said}"]
    for name in ("git", "claude"):
        found = which(name)
        if found:
            ctx.tools[name] = found
        else:
            lines.append(f"note: no `{name}` on PATH -- {_install_hint(name)}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv/Scripts/python -m pytest tests/test_install.py -q
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "install.py: the spine, and prerequisites checked never installed"
```

---

### Task 4: The venv, the Python packages, Playwright — **DONE 2026-09-11**

> Run for real against the working checkout: venv skipped (3.13) in 0.0s;
> packages 1.6s the first time (pip: all satisfied; then stamped), 0.0s
> the second; Playwright 0.3s with Chromium already present — the
> always-run step costs nothing when there is nothing to do.

**Files:**
- Modify: `install.py` (append)
- Test: `tests/test_install.py` (append)

**Interfaces:**
- Consumes: Task 3's `Context`, `run`, `must`, `StepFailed`, `STAMP`, `MIN_PYTHON`, `_version`
- Produces:
  - `venv_python(root: Path) -> Path | None`
  - `_digest(files: list[Path]) -> str`, `_is_current(target: Path, digest: str) -> bool`, `_stamp(target: Path, digest: str) -> None`
  - `REQUIREMENTS = ("requirements.txt", "requirements-piper.txt", "requirements-stt.txt")`
  - steps `venv(ctx)`, `python_packages(ctx)`, `playwright(ctx)`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_install.py`)

```python
# --- the venv ----------------------------------------------------------------

def fake_venv(root, name=("Scripts", "python.exe")):
    exe = root / ".venv" / Path(*name)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    return exe


def says_python(version):
    return lambda argv: argv[1:2] == ["-c"] and "version_info" in argv[2], ok(version)


def test_a_missing_venv_is_created_from_the_running_interpreter(tmp_path, rec):
    rec.reply(lambda a: a[1:3] == ["-m", "venv"], ok(),
              effect=lambda *_: fake_venv(tmp_path))
    status = install.venv(make_ctx(tmp_path))
    assert rec.argvs()[0] == ["/fake/python3", "-m", "venv", str(tmp_path / ".venv")]
    assert status.startswith("created")


def test_an_existing_venv_is_kept(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(*says_python("3.13\n"))
    status = install.venv(make_ctx(tmp_path))
    assert not any(a[1:3] == ["-m", "venv"] for a in rec.argvs())
    assert status.startswith("skipped")


def test_a_venv_too_old_for_jarvis_is_refused_not_used(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(*says_python("3.10\n"))
    with pytest.raises(install.StepFailed, match="Delete .venv"):
        install.venv(make_ctx(tmp_path))


def test_the_venv_interpreter_is_found_under_either_platforms_name(tmp_path):
    exe = fake_venv(tmp_path, ("bin", "python"))
    assert install.venv_python(tmp_path) == exe


# --- Python packages ---------------------------------------------------------

def fake_requirements(root):
    for name in install.REQUIREMENTS:
        (root / name).write_text(f"# {name}\n")


def is_pip(argv):
    return argv[1:4] == ["-m", "pip", "install"]


def test_packages_install_all_three_files_through_the_venv(tmp_path, rec):
    exe = fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    (argv,) = [a for a in rec.argvs() if is_pip(a)]
    assert argv[0] == str(exe)
    assert argv[4:] == ["-r", "requirements.txt", "-r", "requirements-piper.txt",
                        "-r", "requirements-stt.txt"]


def test_unchanged_requirements_are_not_reinstalled(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    status = install.python_packages(make_ctx(tmp_path))
    assert sum(is_pip(a) for a in rec.argvs()) == 1
    assert status.startswith("skipped")


def test_a_changed_requirements_file_reinstalls(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    (tmp_path / "requirements-stt.txt").write_text("faster-whisper==9\n")
    install.python_packages(make_ctx(tmp_path))
    assert sum(is_pip(a) for a in rec.argvs()) == 2


def test_the_stamp_lives_inside_the_venv_so_deleting_it_forgets_it(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    assert (tmp_path / ".venv" / install.STAMP).is_file()


def test_a_failed_pip_stops_and_stamps_nothing(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    rec.reply(is_pip, install.Result(1, "", "No matching distribution"))
    with pytest.raises(install.StepFailed):
        install.python_packages(make_ctx(tmp_path))
    assert not (tmp_path / ".venv" / install.STAMP).exists()


# --- Playwright --------------------------------------------------------------

def test_playwright_installs_chromium_through_the_venv(tmp_path, rec):
    exe = fake_venv(tmp_path)
    install.playwright(make_ctx(tmp_path))
    assert rec.argvs() == [[str(exe), "-m", "playwright", "install", "chromium"]]
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/Scripts/python -m pytest tests/test_install.py -q
```

Expected: the new tests FAIL with `AttributeError: module 'install' has no
attribute 'venv'` (and `venv_python`, `REQUIREMENTS`, ...).

- [ ] **Step 3: Implement** (append to `install.py`)

```python
REQUIREMENTS = ("requirements.txt", "requirements-piper.txt", "requirements-stt.txt")


def venv_python(root: Path) -> Path | None:
    """The venv's interpreter under EITHER platform's name -- both tried,
    never chosen by platform (electron/python.js follows the same rule)."""
    for rel in (Path(".venv", "Scripts", "python.exe"), Path(".venv", "bin", "python")):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _digest(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _is_current(target: Path, digest: str) -> bool:
    """Whether `target` was last built from inputs with this digest. The stamp
    lives INSIDE the thing it describes: delete the venv, or node_modules, and
    the stamp goes with it rather than vouching for something that is gone."""
    try:
        return (target / STAMP).read_text(encoding="utf-8").strip() == digest
    except OSError:
        return False


def _stamp(target: Path, digest: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / STAMP).write_text(digest + "\n", encoding="utf-8")


def venv(ctx: Context) -> str:
    found = venv_python(ctx.root)
    if found is None:
        argv = [ctx.python, "-m", "venv", str(ctx.root / ".venv")]
        must(run(argv, cwd=ctx.root), argv, "could not create .venv")
        found = venv_python(ctx.root)
        if found is None:
            raise StepFailed("created .venv, but found no interpreter inside it")
        return f"created .venv ({found})"
    argv = [str(found), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]
    said = must(run(argv), argv, "the existing .venv's Python would not run").stdout.strip()
    got = _version(said)
    if got is None or got[:2] < MIN_PYTHON:
        raise StepFailed(f"the existing .venv is Python {said or 'unknown'}; JARVIS needs "
                         f"3.11 or newer. Delete .venv and run install.py again.")
    return f"skipped: .venv already exists (Python {said})"


def python_packages(ctx: Context) -> str:
    """All three requirements files: the voice and the ear are optional for a
    Chrome JARVIS, but the desktop application is what this sets up."""
    exe = venv_python(ctx.root)
    digest = _digest([ctx.root / name for name in REQUIREMENTS])
    target = ctx.root / ".venv"
    if _is_current(target, digest):
        return "skipped: requirements unchanged since the last install"
    argv = [str(exe), "-m", "pip", "install"]
    for name in REQUIREMENTS:
        argv += ["-r", name]
    must(run(argv, cwd=ctx.root), argv, "pip could not install the requirements")
    _stamp(target, digest)
    return "installed " + ", ".join(REQUIREMENTS)


def playwright(ctx: Context) -> str:
    """Always run: Playwright's own installer skips a browser it already has,
    which beats guessing where it keeps them (PLAYWRIGHT_BROWSERS_PATH moves
    them). The fresh-clone run in Task 12 times it."""
    argv = [str(venv_python(ctx.root)), "-m", "playwright", "install", "chromium"]
    must(run(argv, cwd=ctx.root), argv, "Playwright could not install Chromium")
    return "Chromium ready"
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv/Scripts/python -m pytest tests/test_install.py -q
```

Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "install.py: the venv, the three requirements files, Playwright"
```

---

### Task 5: `.env` — created when missing, diagnosed never edited — **DONE 2026-09-11**

> **One addition beyond the code below**, found by running it: the block is
> APPENDED to `.env.example`, and the server takes the FIRST occurrence of a
> key — so a live `JARVIS_STT_BACKEND=browser` ever added to the example
> would silently override it and leave a freshly installed application deaf.
> `dotenv` now judges the file it created as the server will read it and
> stops if that happens (`test_a_created_env_that_an_example_line_would_override_is_a_stop`,
> watched failing first). **Every later "Expected: N passed" is one higher.**
>
> Run for real: the working checkout's `.env` was reported fine and its hash
> was unchanged; a `.env` created from the real `.env.example` got whisper,
> and piper because this box has no `say`.

**Files:**
- Modify: `install.py` (append)
- Test: `tests/test_install.py` (append)

**Interfaces:**
- Consumes: Task 2's `env_file.parse_env_lines`; Task 3's `Context`, `which`
- Produces:
  - `env_path(ctx: Context) -> Path`
  - `effective_env(ctx: Context) -> dict[str, str]` — the environment the SERVER will run with. Used by Tasks 6 and 9.
  - `env_problems(env: dict[str, str], have_say: bool) -> list[str]`
  - step `dotenv(ctx)`

- [ ] **Step 1: Write the failing tests** (append)

```python
# --- .env --------------------------------------------------------------------

EXAMPLE = "# JARVIS configuration\n# JARVIS_TTS_BACKEND=say\nUSER_NAME=\n"


def with_example(root):
    (root / ".env.example").write_text(EXAMPLE)
    return root


def say_is(present, monkeypatch):
    monkeypatch.setattr(install, "which", lambda n: "/usr/bin/say" if (n == "say" and present) else None)


def test_a_missing_env_is_made_from_the_example_with_the_ear_the_app_needs(tmp_path, monkeypatch):
    say_is(True, monkeypatch)
    install.dotenv(make_ctx(with_example(tmp_path)))
    text = (tmp_path / ".env").read_text()
    assert text.startswith(EXAMPLE)
    assert "\nJARVIS_STT_BACKEND=whisper\n" in text
    assert "\nJARVIS_TTS_BACKEND=piper\n" not in text, "say exists here; the default voice works"


def test_without_say_the_new_env_names_a_voice_that_exists(tmp_path, monkeypatch):
    say_is(False, monkeypatch)
    install.dotenv(make_ctx(with_example(tmp_path)))
    assert "\nJARVIS_TTS_BACKEND=piper\n" in (tmp_path / ".env").read_text()


def test_jarvis_env_file_decides_which_file(tmp_path, monkeypatch):
    say_is(True, monkeypatch)
    elsewhere = tmp_path / "elsewhere" / ".env"
    install.dotenv(make_ctx(with_example(tmp_path), env={"JARVIS_ENV_FILE": str(elsewhere)}))
    assert elsewhere.exists() and not (tmp_path / ".env").exists()


def test_an_existing_env_is_never_changed_only_diagnosed(tmp_path, monkeypatch):
    say_is(False, monkeypatch)
    original = b"JARVIS_STT_BACKEND=browser\r\n# mine\r\n"
    (with_example(tmp_path) / ".env").write_bytes(original)
    status = install.dotenv(make_ctx(tmp_path))
    assert (tmp_path / ".env").read_bytes() == original
    assert "hear nothing" in status and "JARVIS_STT_BACKEND=whisper" in status
    assert "will not speak" in status and "JARVIS_TTS_BACKEND=piper" in status


def test_a_good_existing_env_is_reported_as_fine(tmp_path, monkeypatch):
    say_is(False, monkeypatch)
    (with_example(tmp_path) / ".env").write_text(
        "JARVIS_STT_BACKEND=whisper\nJARVIS_TTS_BACKEND=piper\n")
    assert "nothing in it" in install.dotenv(make_ctx(tmp_path))


def test_the_effective_env_is_the_servers_process_first_then_first_line():
    """server.py loads .env with os.environ.setdefault per line: the process
    environment wins, and within the file the FIRST occurrence does."""
    ctx = make_ctx(Path("."), env={"JARVIS_STT_BACKEND": "whisper"})
    lines = "JARVIS_STT_BACKEND=browser\nUSER_NAME=Ken\nUSER_NAME=Other\n"
    got = install._merge_env(ctx.env, lines)
    assert got["JARVIS_STT_BACKEND"] == "whisper" and got["USER_NAME"] == "Ken"


def test_fish_without_a_key_on_a_machine_without_say_is_mute():
    problems = install.env_problems(
        {"JARVIS_STT_BACKEND": "whisper", "JARVIS_TTS_BACKEND": "fish"}, have_say=False)
    assert any("will not speak" in p for p in problems)
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/Scripts/python -m pytest tests/test_install.py -q
```

Expected: the new tests FAIL — `AttributeError: module 'install' has no attribute 'dotenv'`.

- [ ] **Step 3: Implement** (append to `install.py`; add `from env_file import parse_env_lines` to the imports at the top)

```python
ENV_BLOCK_HEAD = "# --- added by install.py: what the desktop application needs on this machine ---"


def env_path(ctx: Context) -> Path:
    """JARVIS_ENV_FILE if set, else the repository's .env -- the server's rule."""
    override = ctx.env.get("JARVIS_ENV_FILE", "").strip()
    return Path(override) if override else ctx.root / ".env"


def _merge_env(process: dict[str, str], dotenv_text: str) -> dict[str, str]:
    """server.py's loader: `os.environ.setdefault` per line, so the process
    environment wins and, within the file, the first occurrence does."""
    merged = dict(process)
    for key, value in parse_env_lines(dotenv_text):
        merged.setdefault(key, value)
    return merged


def effective_env(ctx: Context) -> dict[str, str]:
    """The environment the SERVER will run with."""
    path = env_path(ctx)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return _merge_env(ctx.env, text)


def env_problems(env: dict[str, str], have_say: bool) -> list[str]:
    """What in this configuration leaves the desktop application deaf or mute
    here, each with the line that fixes it."""
    out = []
    stt = (env.get("JARVIS_STT_BACKEND") or "browser").strip().lower()
    if stt != "whisper":
        out.append(f"JARVIS_STT_BACKEND is {stt!r}: the desktop application will hear "
                   f"nothing (Electron has no speech service). Add: JARVIS_STT_BACKEND=whisper")
    tts = (env.get("JARVIS_TTS_BACKEND") or "say").strip().lower()
    if tts == "fish" and not env.get("FISH_API_KEY", "").strip():
        tts = "say"                     # tts.py falls back to `say` without a key
    if tts not in ("piper", "fish") and not have_say:
        out.append(f"JARVIS_TTS_BACKEND is {tts!r} and there is no `say` on this machine: "
                   f"JARVIS will not speak. Add: JARVIS_TTS_BACKEND=piper")
    return out


def dotenv(ctx: Context) -> str:
    """Create a missing .env; NEVER modify an existing one. A program that
    rewrites configuration behind you is harder to trust than one that
    explains (phase 5's rule)."""
    path = env_path(ctx)
    have_say = which("say") is not None
    if path.exists():
        problems = env_problems(effective_env(ctx), have_say)
        if not problems:
            return f"kept {path}; nothing in it stops the application hearing or speaking"
        return f"kept {path} unchanged -- but:\n" + "\n".join(f"  {p}" for p in problems)
    block = ["", ENV_BLOCK_HEAD,
             "# Electron has no speech service: the browser's recogniser hears nothing there.",
             "JARVIS_STT_BACKEND=whisper"]
    if not have_say:
        block += ["# There is no `say` on this machine, so the default voice would be silence.",
                  "JARVIS_TTS_BACKEND=piper"]
    example = (ctx.root / ".env.example").read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example.rstrip("\n") + "\n" + "\n".join(block) + "\n", encoding="utf-8")
    added = [line for line in block if line and not line.startswith("#")]
    return f"created {path} from .env.example, adding " + ", ".join(added)
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
.venv/Scripts/python -m pytest tests/test_install.py -q
```

Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "install.py: create a missing .env; diagnose, never edit, an existing one"
```

---

### Task 6: The models JARVIS will actually load — **DONE 2026-09-11**

> Run for real against the working checkout: the probe, through the venv
> with the server's environment, answered `en_GB-alan-medium` present in
> this checkout's `data/voices` and `base.en` cached; the step skipped in
> 0.3s. `piper.download_voices --download-dir` and
> `WhisperModel(model_size_or_path, device, ..., compute_type)` confirmed to
> exist as called. The real downloads happen in Task 12's fresh clone.

**Files:**
- Modify: `install.py` (append)
- Test: `tests/test_install.py` (append)

**Interfaces:**
- Consumes: `venv_python`, `effective_env`, `run`, `must`, `StepFailed`
- Produces: `PROBE_MODELS: str`, `FETCH_WHISPER: str`, `_probe_models(ctx, exe, env) -> dict`, step `models(ctx)`

"Present" is decided by JARVIS's own functions, run through the venv with the
server's environment — so a `JARVIS_DATA_DIR`, `JARVIS_PIPER_VOICE` or
`JARVIS_STT_MODEL` in `.env` is honoured exactly as the server will honour it.

- [ ] **Step 1: Write the failing tests** (append)

```python
# --- models ------------------------------------------------------------------

import json as _json


def probe_says(**kw):
    # voices_dir is only ever created when the voice is missing; every test
    # that says so passes its own tmp directory.
    found = {"voice": "en_GB-alan-medium", "voice_present": True,
             "voices_dir": "/never-created", "stt_model": "base.en", "stt_present": True}
    found.update(kw)
    return ok("some import-time log line\n" + _json.dumps(found) + "\n")


def is_probe(argv):
    return argv[1:2] == ["-c"] and argv[2] == install.PROBE_MODELS


def test_models_already_present_download_nothing(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(is_probe, probe_says())
    status = install.models(make_ctx(tmp_path))
    assert rec.argvs() == [[str(tmp_path / ".venv" / "Scripts" / "python.exe"), "-c", install.PROBE_MODELS]]
    assert status.startswith("skipped")


def test_a_missing_voice_is_downloaded_by_its_configured_name(tmp_path, rec):
    exe = fake_venv(tmp_path)
    rec.reply(is_probe, [probe_says(voice="en_US-amy-low", voice_present=False,
                                    voices_dir=str(tmp_path / "voices")),
                         probe_says(voice="en_US-amy-low")])
    install.models(make_ctx(tmp_path))
    assert [str(exe), "-m", "piper.download_voices", "--download-dir",
            str(tmp_path / "voices"), "en_US-amy-low"] in rec.argvs()


def test_a_missing_whisper_model_is_fetched_by_its_configured_name(tmp_path, rec):
    exe = fake_venv(tmp_path)
    rec.reply(is_probe, [probe_says(stt_model="small.en", stt_present=False),
                         probe_says(stt_model="small.en")])
    install.models(make_ctx(tmp_path))
    assert [str(exe), "-c", install.FETCH_WHISPER, "small.en"] in rec.argvs()


def test_a_voice_named_as_a_missing_file_is_a_stop_not_a_download(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(is_probe, probe_says(voice="/models/mine.onnx", voice_present=False))
    with pytest.raises(install.StepFailed, match="does not exist"):
        install.models(make_ctx(tmp_path))
    assert not any("piper.download_voices" in a for a in rec.argvs())


def test_the_probe_runs_with_the_servers_environment(tmp_path, rec):
    fake_venv(tmp_path)
    (tmp_path / ".env").write_text("JARVIS_PIPER_VOICE=en_US-amy-low\n")
    rec.reply(is_probe, probe_says())
    install.models(make_ctx(tmp_path))
    assert rec.calls[0]["env"]["JARVIS_PIPER_VOICE"] == "en_US-amy-low"


def test_a_download_jarvis_still_cannot_find_is_a_stop(tmp_path, rec):
    fake_venv(tmp_path)
    # Still missing afterwards. A tmp voices_dir: the step creates it.
    rec.reply(is_probe, probe_says(voice_present=False, voices_dir=str(tmp_path / "voices")))
    with pytest.raises(install.StepFailed, match="still cannot find"):
        install.models(make_ctx(tmp_path))
```

- [ ] **Step 2: Run them and watch them fail**

Expected: FAIL — `AttributeError: module 'install' has no attribute 'PROBE_MODELS'`.

- [ ] **Step 3: Implement** (append)

```python
# Asked of JARVIS itself, through the venv: "present" means what the server
# will find, not what this script believes. One JSON line, printed last, so
# anything a module logs at import time cannot be mistaken for the answer.
PROBE_MODELS = (
    "import json, data_paths, stt, tts\n"
    "print(json.dumps({'voice': tts.resolve_piper_voice(),"
    " 'voice_present': tts.piper_model_path() is not None,"
    " 'voices_dir': str(data_paths.voices_dir()),"
    " 'stt_model': stt.resolve_model(),"
    " 'stt_present': stt.model_is_cached()}))"
)
# The model name arrives as an ARGUMENT, never spliced into the code.
FETCH_WHISPER = (
    "import sys\n"
    "from faster_whisper import WhisperModel\n"
    "WhisperModel(sys.argv[1], device='cpu', compute_type='int8')"
)


def _probe_models(ctx: Context, exe: Path, env: dict[str, str]) -> dict:
    argv = [str(exe), "-c", PROBE_MODELS]
    result = must(run(argv, cwd=ctx.root, env=env), argv,
                  "could not ask JARVIS which models it will load")
    return json.loads(result.stdout.strip().splitlines()[-1])


def models(ctx: Context) -> str:
    exe = venv_python(ctx.root)
    env = effective_env(ctx)
    found = _probe_models(ctx, exe, env)
    fetched = []
    if not found["voice_present"]:
        voice = found["voice"]
        if "/" in voice or "\\" in voice or voice.endswith(".onnx"):
            raise StepFailed(f"JARVIS_PIPER_VOICE names a file that does not exist: {voice}")
        Path(found["voices_dir"]).mkdir(parents=True, exist_ok=True)
        argv = [str(exe), "-m", "piper.download_voices", "--download-dir",
                found["voices_dir"], voice]
        must(run(argv, cwd=ctx.root, env=env), argv, f"could not download the piper voice {voice}")
        fetched.append(f"voice {voice}")
    if not found["stt_present"]:
        argv = [str(exe), "-c", FETCH_WHISPER, found["stt_model"]]
        must(run(argv, cwd=ctx.root, env=env), argv,
             f"could not fetch the whisper model {found['stt_model']}")
        fetched.append(f"whisper {found['stt_model']}")
    if not fetched:
        return f"skipped: voice {found['voice']} and whisper {found['stt_model']} already present"
    again = _probe_models(ctx, exe, env)
    missing = [name for name, key in (("the voice", "voice_present"), ("the whisper model", "stt_present"))
               if not again[key]]
    if missing:
        raise StepFailed("downloaded, but JARVIS still cannot find " + " or ".join(missing))
    return "downloaded " + ", ".join(fetched)
```

- [ ] **Step 4: Run the tests and watch them pass**

Expected: 32 passed.

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "install.py: fetch the models JARVIS will load, as JARVIS judges them"
```

---

### Task 7: The frontend and Electron — **DONE 2026-09-11**

> **Step 1 measured:** with the application running from this checkout
> (against the silent stand-in), `npm ci` in `electron/` failed with
> **`EPERM`** (`syscall unlink`, `errno -4048`) on
> `node_modules/electron/dist/d3dcompiler_47.dll` — after deleting whatever
> it could, leaving the tree broken until `npm ci` and `install.js` ran again
> with the app quit. `BUSY_MARKERS` keeps `EBUSY` beside the measured
> `EPERM`.
>
> **Run for real, twice:** frontend 6.9s (`npm ci` + build) then 2.0s (build
> only); Electron 2.1s (`npm ci` + **unpacked the binary** — `npm ci` really
> does leave none) then 0.0s. Stamps written inside both `node_modules`.

**Files:**
- Modify: `install.py` (append)
- Test: `tests/test_install.py` (append)

**Interfaces:**
- Consumes: `_digest`, `_is_current`, `_stamp`, `run`, `must`, `ctx.tools["npm"]`, `ctx.tools["node"]`
- Produces: `_npm_ci(ctx, where: Path) -> bool` (True if it installed), `electron_exe(root: Path) -> Path | None` (used by Task 8), steps `frontend(ctx)`, `electron(ctx)`

- [ ] **Step 1: Measure how `npm ci` fails while JARVIS is running**

The spec leaves this to the plan "after seeing how it actually fails". Start
the application against the silent stand-in from phase 5 (a blank page, no
microphone) so it holds `electron.exe` open, then run npm over it:

```bash
node -e "require('http').createServer((q,r)=>{if(q.url==='/api/health'){r.writeHead(200,{'content-type':'application/json'});return r.end(JSON.stringify({status:'online',name:'JARVIS',version:'0.1.0'}))}r.writeHead(200,{'content-type':'text/html'});r.end('<title>JARVIS</title>stand-in')}).listen(8341,'127.0.0.1')" &
cd electron && JARVIS_ORIGIN=http://127.0.0.1:8341 npm start &
cd electron && npm ci; echo "exit $?"
```

Record the error code npm prints (expected `EBUSY` or `EPERM`). Quit the app
from the tray, stop the stand-in, and repair the tree with `npm ci` and
`node node_modules/electron/install.js`. **If the code is something else, use
that string in Step 3 and in the test.**

- [ ] **Step 2: Write the failing tests** (append)

```python
# --- frontend and Electron ---------------------------------------------------

def npm_ctx(root):
    for where in ("frontend", "electron"):
        (root / where).mkdir(exist_ok=True)
        (root / where / "package-lock.json").write_text('{"lockfileVersion": 3}')
    return make_ctx(root, tools={"npm": "/fake/bin/npm.cmd", "node": "/fake/bin/node"})


def test_the_frontend_is_installed_by_its_lockfile_then_built(tmp_path, rec):
    ctx = npm_ctx(tmp_path)
    install.frontend(ctx)
    assert rec.argvs() == [["/fake/bin/npm.cmd", "ci"], ["/fake/bin/npm.cmd", "run", "build"]]
    assert rec.calls[0]["cwd"] == tmp_path / "frontend"


def test_an_unchanged_lockfile_skips_the_install_but_never_the_build(tmp_path, rec):
    """A pull can change frontend/src without touching the lockfile."""
    ctx = npm_ctx(tmp_path)
    install.frontend(ctx)
    rec.calls.clear()
    install.frontend(ctx)
    assert rec.argvs() == [["/fake/bin/npm.cmd", "run", "build"]]


def test_a_busy_node_modules_says_to_quit_jarvis(tmp_path, rec):
    ctx = npm_ctx(tmp_path)
    rec.reply(lambda a: a[1:] == ["ci"],
              install.Result(1, "", "npm error code EBUSY\nnpm error syscall rmdir"))
    with pytest.raises(install.StepFailed, match="quit it from the tray"):
        install.electron(ctx)


def fake_electron_binary(root):
    pkg = root / "electron" / "node_modules" / "electron"
    (pkg / "dist").mkdir(parents=True, exist_ok=True)
    (pkg / "path.txt").write_text("electron.exe")
    (pkg / "dist" / "electron.exe").write_text("")


def is_unpack(argv):
    return argv[0] == "/fake/bin/node" and argv[1].endswith("install.js")


def test_electron_is_unpacked_when_its_binary_is_missing(tmp_path, rec):
    ctx = npm_ctx(tmp_path)
    rec.reply(is_unpack, ok(), effect=lambda *_: fake_electron_binary(tmp_path))
    install.electron(ctx)
    assert any(is_unpack(a) for a in rec.argvs())
    assert install.electron_exe(tmp_path) == tmp_path / "electron" / "node_modules" / "electron" / "dist" / "electron.exe"


def test_an_unpacked_electron_is_not_unpacked_again(tmp_path, rec):
    ctx = npm_ctx(tmp_path)
    fake_electron_binary(tmp_path)
    install.electron(ctx)
    assert not any(is_unpack(a) for a in rec.argvs())


def test_an_unpack_that_leaves_no_binary_is_a_stop(tmp_path, rec):
    ctx = npm_ctx(tmp_path)
    with pytest.raises(install.StepFailed, match="no binary"):
        install.electron(ctx)
```

- [ ] **Step 3: Run them and watch them fail**

Expected: FAIL — `AttributeError: module 'install' has no attribute 'frontend'`.

- [ ] **Step 4: Implement** (append)

```python
# The error codes npm reports when Windows will not let it delete a file that
# is in use -- measured in Task 7 Step 1 with JARVIS running.
BUSY_MARKERS = ("EBUSY", "EPERM")


def _npm_ci(ctx: Context, where: Path) -> bool:
    """`npm ci` by the lockfile, skipped when the lockfile is what the last
    successful install used. Returns whether it installed."""
    digest = _digest([where / "package-lock.json"])
    modules = where / "node_modules"
    if _is_current(modules, digest):
        return False
    argv = [ctx.tools["npm"], "ci"]
    result = run(argv, cwd=where)
    if result.returncode != 0:
        if any(marker in result.output for marker in BUSY_MARKERS):
            raise StepFailed(f"npm could not replace {where.name}/node_modules -- something in it "
                             f"is in use. If JARVIS is running, quit it from the tray and run "
                             f"install.py again.", [str(a) for a in argv], result.output)
        raise StepFailed(f"npm ci failed in {where.name}/", [str(a) for a in argv], result.output)
    _stamp(modules, digest)
    return True


def frontend(ctx: Context) -> str:
    """The application loads the page the server serves out of frontend/dist.
    The build always runs: a pull can change the source without the lockfile."""
    where = ctx.root / "frontend"
    installed = _npm_ci(ctx, where)
    argv = [ctx.tools["npm"], "run", "build"]
    must(run(argv, cwd=where), argv, "the frontend build failed")
    return ("installed dependencies and " if installed else "dependencies unchanged; ") + "built frontend/dist"


def electron_exe(root: Path) -> Path | None:
    """The unpacked Electron binary, found the way Electron finds it: through
    the path.txt its installer writes (electron/index.js)."""
    package = root / "electron" / "node_modules" / "electron"
    try:
        relative = (package / "path.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    exe = package / "dist" / relative
    return exe if relative and exe.exists() else None


def electron(ctx: Context) -> str:
    """`npm ci` does not unpack the binary (found in phase 5); install.js does."""
    where = ctx.root / "electron"
    installed = _npm_ci(ctx, where)
    unpacked = False
    if electron_exe(ctx.root) is None:
        argv = [ctx.tools["node"], str(Path("node_modules", "electron", "install.js"))]
        must(run(argv, cwd=where), argv, "could not unpack the Electron binary")
        if electron_exe(ctx.root) is None:
            raise StepFailed("Electron's installer ran but left no binary")
        unpacked = True
    parts = ["installed dependencies" if installed else "dependencies unchanged",
             "unpacked the binary" if unpacked else "binary present"]
    return "; ".join(parts)
```

- [ ] **Step 5: Run the tests and watch them pass**

Expected: 38 passed.

- [ ] **Step 6: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "install.py: the frontend and Electron, by their lockfiles"
```

---

### Task 8: The Start-menu entry

**Files:**
- Create: `electron/jarvis.ico`
- Modify: `install.py` (append)
- Test: `tests/test_install.py` (append)

**Interfaces:**
- Consumes: `electron_exe`, `which`, `run`, `must`
- Produces: `SHORTCUT_PS1: str`, `start_menu(ctx) -> Path | None`, step `shortcut(ctx)`

- [ ] **Step 1: Make the icon**

A throwaway generator, run once; only its output is committed. Save as
`.agents/make_icon.py` (Write tool) and run it with any Python:

```python
# THROWAWAY. electron/jarvis.ico: the tray ring at 16, 32, 48 and 256 px,
# as PNGs inside an ICO container (Windows Vista and later read those).
import math
import struct
import zlib


def ring_png(size):
    rows = []
    c = size / 2
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = math.hypot(x + 0.5 - c, y + 0.5 - c) * 32 / size
            a = max(0.0, 1.0 - abs(d - 11.0) / 2.2)
            a = max(a, max(0.0, 1.0 - d / 4.5) * 0.9)
            row += bytes([79, 209, 255, int(round(255 * min(1.0, a)))])
        rows.append(bytes(row))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


sizes = [16, 32, 48, 256]
images = [ring_png(s) for s in sizes]
offset = 6 + 16 * len(sizes)
entries, data = b"", b""
for size, image in zip(sizes, images):
    entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                           len(image), offset + len(data))
    data += image
with open("electron/jarvis.ico", "wb") as fh:
    fh.write(struct.pack("<HHH", 0, 1, len(sizes)) + entries + data)
print("wrote electron/jarvis.ico")
```

```bash
python .agents/make_icon.py && rm .agents/make_icon.py
```

Check the container (the Read tool cannot open an `.ico`):

```bash
python -c "import struct; b=open('electron/jarvis.ico','rb').read(); n=struct.unpack('<HHH',b[:6])[2]; print([(struct.unpack('<B',b[6+16*k:7+16*k])[0] or 256, b[struct.unpack('<I',b[18+16*k:22+16*k])[0]:][:4]==b'\x89PNG') for k in range(n)])"
```

Expected: `[(16, True), (32, True), (48, True), (256, True)]` — checked when
this plan was written, 27,771 bytes.

- [ ] **Step 2: Write the failing tests** (append)

```python
# --- the Start-menu entry ----------------------------------------------------

def start_menu_ctx(root):
    programs = root / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True)
    fake_electron_binary(root)
    return make_ctx(root, env={"APPDATA": str(root / "appdata")}), programs


def with_powershell(monkeypatch):
    monkeypatch.setattr(install, "which",
                        lambda n: "/fake/powershell.exe" if n == "powershell" else None)


def test_the_shortcut_launches_this_checkouts_electron_with_the_app(tmp_path, rec, monkeypatch):
    with_powershell(monkeypatch)
    ctx, programs = start_menu_ctx(tmp_path)
    install.shortcut(ctx)
    (call,) = rec.calls
    assert call["argv"][0] == "/fake/powershell.exe" and call["argv"][-1] == install.SHORTCUT_PS1
    env = call["env"]
    assert env["JARVIS_LNK"] == str(programs / "JARVIS.lnk")
    assert env["JARVIS_TARGET"] == str(install.electron_exe(tmp_path))
    assert env["JARVIS_APP"] == str(tmp_path / "electron")
    assert env["JARVIS_ICON"] == str(tmp_path / "electron" / "jarvis.ico")


def test_paths_reach_powershell_only_through_its_environment(tmp_path, rec, monkeypatch):
    """Phase 3's launcher lesson: a shell that re-parses a path will one day
    meet one it breaks on. No path is ever part of the script's text."""
    with_powershell(monkeypatch)
    odd = tmp_path / "Ken's $HOME & 100% (copy)"
    odd.mkdir()
    ctx, _ = start_menu_ctx(odd)
    install.shortcut(ctx)
    (call,) = rec.calls
    assert not any(str(odd) in a or "Ken's" in a for a in call["argv"])
    assert "$env:JARVIS_LNK" in install.SHORTCUT_PS1


def test_where_there_is_no_start_menu_it_says_how_to_launch(tmp_path, rec, monkeypatch):
    with_powershell(monkeypatch)
    fake_electron_binary(tmp_path)
    status = install.shortcut(make_ctx(tmp_path, env={}))
    assert rec.calls == [] and "npm start" in status


def test_no_powershell_is_a_stop(tmp_path, rec, monkeypatch):
    monkeypatch.setattr(install, "which", lambda n: None)
    ctx, _ = start_menu_ctx(tmp_path)
    with pytest.raises(install.StepFailed, match="powershell"):
        install.shortcut(ctx)
```

- [ ] **Step 3: Run them and watch them fail**

Expected: FAIL — `AttributeError: module 'install' has no attribute 'shortcut'`.

- [ ] **Step 4: Implement** (append; Write/Edit tool — the script has no
backslashes, but the surrounding file does)

```python
# Every path arrives as an environment variable. None is ever part of this
# text: phase 3 found a launcher whose quoting had never worked, because a
# shell re-parsed a path it was handed inside a command line.
SHORTCUT_PS1 = (
    "$ErrorActionPreference = 'Stop'\n"
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:JARVIS_LNK)\n"
    "$s.TargetPath = $env:JARVIS_TARGET\n"
    "$s.Arguments = '\"' + $env:JARVIS_APP + '\"'\n"
    "$s.WorkingDirectory = $env:JARVIS_APP\n"
    "$s.IconLocation = $env:JARVIS_ICON\n"
    "$s.Description = 'JARVIS'\n"
    "$s.Save()\n"
)


def start_menu(ctx: Context) -> Path | None:
    """The per-user Start-menu Programs folder, if this machine has one --
    asked of the machine rather than of its operating system's name."""
    appdata = ctx.env.get("APPDATA", "").strip()
    if not appdata:
        return None
    programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programs if programs.is_dir() else None


def shortcut(ctx: Context) -> str:
    """Rewritten on every run, so a moved checkout is mended the way it was
    installed. macOS: prints the launch command -- a Mac .app is out of scope."""
    app_dir = ctx.root / "electron"
    programs = start_menu(ctx)
    if programs is None:
        return f"no Start menu here; launch JARVIS with:  cd \"{app_dir}\" && npm start"
    exe = electron_exe(ctx.root)
    if exe is None:
        raise StepFailed("no Electron binary to point the shortcut at")
    powershell = which("powershell")
    if not powershell:
        raise StepFailed("no `powershell` on PATH to write the Start-menu shortcut with")
    link = programs / "JARVIS.lnk"
    env = dict(ctx.env, JARVIS_LNK=str(link), JARVIS_TARGET=str(exe),
               JARVIS_APP=str(app_dir), JARVIS_ICON=str(app_dir / "jarvis.ico"))
    argv = [powershell, "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_PS1]
    must(run(argv, env=env), argv, "PowerShell could not write the shortcut")
    return f"wrote {link}"
```

- [ ] **Step 5: Run the tests and watch them pass**

Expected: 42 passed.

- [ ] **Step 6: Check it for real, once**

The tests prove what is sent; this proves Windows accepts it. From the repo:

```bash
.venv/Scripts/python -c "import install, os; ctx = install.Context(root=install.REPO, env=dict(os.environ)); print(install.shortcut(ctx))"
powershell -NoProfile -Command '$s=(New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\JARVIS.lnk"); $s.TargetPath; $s.Arguments; $s.IconLocation'
```

Expected: `wrote ...JARVIS.lnk`, then this checkout's `electron.exe`, the
quoted `electron` folder, and `jarvis.ico`. Launch "JARVIS" from the Start
menu once — silent check: against the stand-in is not possible from a
shortcut, so this launches the real JARVIS; if Ken is not free for audio, do
this in Task 12 instead.

- [ ] **Step 7: Commit**

```bash
git add install.py tests/test_install.py electron/jarvis.ico
git commit -m "install.py: a Start-menu entry, its paths never in the script text"
```

---

### Task 9: Preflight, and `main()`

**Files:**
- Modify: `install.py` (append)
- Test: `tests/test_install.py` (append)

**Interfaces:**
- Consumes: every step above; `effective_env`
- Produces: `PREFLIGHT: str`, step `checks(ctx)`, `STEPS: list[tuple[str, Callable]]`, `main(*, root: Path = REPO, env: dict | None = None) -> int`

- [ ] **Step 1: Write the failing tests** (append)

```python
# --- preflight and main ------------------------------------------------------

def test_preflight_reports_every_check_with_its_remedy(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(lambda a: a[1:2] == ["-c"] and a[2] == install.PREFLIGHT, ok(_json.dumps([
        {"name": "claude_cli", "status": "ok", "message": "claude 2.1.300", "remedy": None},
        {"name": "claude_login", "status": "fail", "message": "not logged in",
         "remedy": "run `claude` and log in"},
    ]) + "\n"))
    status = install.checks(make_ctx(tmp_path))
    assert status.startswith("1 check(s) need attention")
    assert "fail claude_login: not logged in" in status and "run `claude` and log in" in status


def test_the_steps_run_in_the_specs_order():
    assert [name for name, _ in install.STEPS] == [
        "prerequisites", "venv", "Python packages", "Playwright Chromium", ".env",
        "models", "frontend", "Electron", "Start-menu shortcut", "preflight"]


def test_main_stops_at_the_first_failure_and_shows_what_failed(tmp_path, monkeypatch, capsys):
    ran = []

    def fine(ctx):
        ran.append("fine")
        return "done"

    def broken(ctx):
        ran.append("broken")
        raise install.StepFailed("it broke", ["/x/tool", "go"], "line 1\nline 2 the reason\n")

    def never(ctx):
        ran.append("never")
        return "done"

    monkeypatch.setattr(install, "STEPS", [("one", fine), ("two", broken), ("three", never)])
    assert install.main(root=tmp_path, env={}) == 1
    assert ran == ["fine", "broken"]
    out = capsys.readouterr().out
    assert "FAILED: it broke" in out and "/x/tool go" in out and "line 2 the reason" in out


def test_main_says_so_when_everything_ran(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(install, "STEPS", [("one", lambda ctx: "done")])
    assert install.main(root=tmp_path, env={}) == 0
    assert "[1/1] one" in capsys.readouterr().out
```

- [ ] **Step 2: Run them and watch them fail**

Expected: FAIL — `AttributeError: module 'install' has no attribute 'PREFLIGHT'`.

- [ ] **Step 3: Implement** (append)

```python
PREFLIGHT = (
    "import asyncio, json, preflight\n"
    "found = asyncio.run(preflight.run_checks())\n"
    "print(json.dumps([{'name': c.name, 'status': c.status, 'message': c.message,"
    " 'remedy': c.remedy} for c in found]))"
)


def checks(ctx: Context) -> str:
    """JARVIS's own first-run checks, through the venv with the server's
    environment. Reported, never a stop: this is the last step, and the most
    likely finding -- Claude Code not logged in -- is Ken's to fix."""
    argv = [str(venv_python(ctx.root)), "-c", PREFLIGHT]
    result = must(run(argv, cwd=ctx.root, env=effective_env(ctx)), argv, "preflight did not run")
    found = json.loads(result.stdout.strip().splitlines()[-1])
    lines = []
    for c in found:
        lines.append(f"  {c['status']} {c['name']}: {c['message']}")
        if c.get("remedy"):
            lines.append(f"       -> {c['remedy']}")
    bad = sum(1 for c in found if c["status"] != "ok")
    head = "all checks passed" if not bad else f"{bad} check(s) need attention"
    return head + "\n" + "\n".join(lines)


STEPS = [
    ("prerequisites", prerequisites),
    ("venv", venv),
    ("Python packages", python_packages),
    ("Playwright Chromium", playwright),
    (".env", dotenv),
    ("models", models),
    ("frontend", frontend),
    ("Electron", electron),
    ("Start-menu shortcut", shortcut),
    ("preflight", checks),
]


def main(*, root: Path = REPO, env: dict | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")     # a tool's output may hold anything
    except AttributeError:
        pass
    ctx = Context(root=root, env=dict(os.environ if env is None else env))
    for number, (name, step) in enumerate(STEPS, 1):
        print(f"[{number}/{len(STEPS)}] {name}", flush=True)
        try:
            status = step(ctx)
        except StepFailed as failure:
            print(f"      FAILED: {failure.message}")
            if failure.command:
                print("      command: " + " ".join(failure.command))
            for line in failure.output.strip().splitlines()[-20:]:
                print("      | " + line)
            print("Stopped. Fix that and run install.py again -- finished steps are skipped.")
            return 1
        for line in status.splitlines():
            print("      " + line, flush=True)
    print("Done. Start JARVIS from the Start menu (or as step 9 said); "
          "run install.py again after every git pull.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and watch them pass**

Expected: 46 passed. Then the whole suite: `.venv/Scripts/python -m pytest` —
expected unchanged apart from these additions (on this box, the four known
`tests/test_specs_api.py` failures, which fail on `main` too).

- [ ] **Step 5: Commit**

```bash
git add install.py tests/test_install.py
git commit -m "install.py: preflight's verdict last, and main() that stops at the first failure"
```

---

### Task 10: "Start with Windows"

**Files:**
- Create: `electron/login.js`
- Test: `electron/test/login.test.js`
- Modify: `electron/main.js` (require block; `createWindow`; `createTray`; `app.whenReady` handler; `warnIfDeaf`)

**Interfaces:**
- Consumes: Task 1's verdict (if it failed, apply its fallback here first)
- Produces: `HIDDEN_FLAG = "--hidden"`, `startAtLoginSupported(platform: string) -> boolean`, `loginItem(execPath: string, appPath: string) -> {path, args}`, `launchedAtLogin(argv: string[]) -> boolean`

- [ ] **Step 1: Write the failing test**

`electron/test/login.test.js` (Write tool — it has backslashes):

```javascript
const { test } = require("node:test");
const assert = require("node:assert");
const { HIDDEN_FLAG, startAtLoginSupported, loginItem, launchedAtLogin } = require("../login");

const EXE = "C:\\repo\\electron\\node_modules\\electron\\dist\\electron.exe";
const APP = "C:\\repo\\electron";

// An unpackaged app: electron.exe alone would start Electron's default app,
// so the entry must name THIS app's directory, and mark the launch as hidden.
test("the login entry launches this app, hidden", () => {
  assert.deepStrictEqual(loginItem(EXE, APP), { path: EXE, args: [APP, HIDDEN_FLAG] });
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
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd electron && npm test
```

Expected: FAIL — `Cannot find module '../login'`.

- [ ] **Step 3: Implement**

`electron/login.js`:

```javascript
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

// Where the checkbox can work. macOS login items take no arguments, so an
// unpackaged app cannot name itself in one; there the checkbox is withdrawn
// rather than shown doing nothing.
function startAtLoginSupported(platform) {
  return platform === "win32";
}

function loginItem(execPath, appPath) {
  return { path: execPath, args: [appPath, HIDDEN_FLAG] };
}

function launchedAtLogin(argv) {
  return argv.includes(HIDDEN_FLAG);
}

module.exports = { HIDDEN_FLAG, startAtLoginSupported, loginItem, launchedAtLogin };
```

- [ ] **Step 4: Run it and watch it pass**

Expected: 44 passed (41 + 3).

- [ ] **Step 5: Wire it into `main.js`** (Edit tool, five edits)

Require block, after `const { findPython } = require("./python");`:

```javascript
const { startAtLoginSupported, loginItem, launchedAtLogin } = require("./login");
```

After `const log = ...`:

```javascript
// Started by Windows at login: the tray, not a window. See login.js.
const STARTED_AT_LOGIN = launchedAtLogin(process.argv);
```

In `createWindow()`, add to the `BrowserWindow` options, beside `title`:

```javascript
      // At login, the tray and not a window -- still listening, which Task 1
      // of phase 6 measured a never-shown window does.
      show: !STARTED_AT_LOGIN,
```

Replace `createTray()` with:

```javascript
  // The login entry, as Windows is asked for it AND as it is read back:
  // getLoginItemSettings on Windows only answers for the same path and args.
  function ourLoginItem() {
    return loginItem(process.execPath, app.getAppPath());
  }

  function trayMenu() {
    const items = [{ label: "Show JARVIS", click: showWindow }];
    if (startAtLoginSupported(process.platform)) {
      items.push({
        label: "Start with Windows",
        type: "checkbox",
        // What Windows reports, not what this process last wrote.
        checked: app.getLoginItemSettings(ourLoginItem()).openAtLogin,
        click: (item) => {
          app.setLoginItemSettings({ ...ourLoginItem(), openAtLogin: item.checked });
          tray.setContextMenu(trayMenu());
        },
      });
    }
    items.push(
      { type: "separator" },
      // Quit must be findable. An application a person cannot work out how
      // to exit is worse than one that simply closes when you close it.
      { label: "Quit JARVIS", click: () => app.quit() },
    );
    return Menu.buildFromTemplate(items);
  }

  function createTray() {
    tray = new Tray(path.join(__dirname, "tray-icon.png"));
    tray.setToolTip("JARVIS (listening)");
    tray.setContextMenu(trayMenu());
    tray.on("double-click", showWindow);
    if (STARTED_AT_LOGIN && process.platform === "win32") {
      tray.displayBalloon({
        title: "JARVIS started with Windows",
        content: "It is listening. Open it from the tray icon.",
        noSound: true,
      });
    }
  }
```

In `warnIfDeaf()`, a warning must not hang off a window nobody can see:

```javascript
      dialog.showMessageBox(win && win.isVisible() ? win : undefined,
                            { type: "warning", title: "JARVIS cannot hear", message: warning });
```

- [ ] **Step 6: Check it, silently first**

Against the stand-in (no microphone, no voice): start it (as in Task 7 Step 1),
then launch the app as Windows would at login:

```bash
cd electron && JARVIS_ORIGIN=http://127.0.0.1:8341 npm start -- --hidden
```

Expected: no window (`jarvis_platform.windows.screen.windows()` lists no
Electron window), the tray icon, the "started with Windows" balloon (Ken's
eyes). Tick "Start with Windows" (Ken), then:

```bash
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
```

Expected: an entry naming this checkout's `electron.exe`, the `electron`
folder, and `--hidden`. Untick it; query again; the entry is gone. Record the
entry verbatim in the commit message.

- [ ] **Step 7: Then through the product's path (Ken, with audio)**

Real JARVIS, launched hidden: `cd electron && npm start -- --hidden`. Speak a
question without opening the window. Expected: JARVIS answers aloud; the
brain's transcript (`~/.claude/projects/*-data-jarvis/`, newest file) shows
it heard. Then Quit from the tray.

- [ ] **Step 8: Commit**

```bash
git add electron/login.js electron/test/login.test.js electron/main.js
git commit -m "electron: Start with Windows, off by default, starting in the tray"
```

---

### Task 11: CI runs the Electron tests

**Files:**
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: `electron/package.json`'s `test` script (quoted glob, fixed in phase 5)
- Produces: nothing further

- [ ] **Step 1: Add the steps** (Edit tool), after the `Frontend build` step:

```yaml
      # electron/'s tests import no Electron -- the logic beside main.js is
      # plain Node -- so the 100 MB binary is not downloaded for them.
      - name: Electron dependencies
        run: npm ci
        working-directory: electron
        env:
          ELECTRON_SKIP_BINARY_DOWNLOAD: "1"

      - name: Electron tests
        run: npm test
        working-directory: electron
```

and widen the npm cache key so the Electron lockfile counts:

```yaml
          cache-dependency-path: |
            frontend/package-lock.json
            electron/package-lock.json
```

- [ ] **Step 2: Check it locally the way CI will run it**

```bash
cd electron && ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci && npm test
```

Expected: all Electron tests pass. Then restore the local binary:
`node node_modules/electron/install.js`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "CI: run the Electron tests, which until now ran only on request"
```

---

### Task 12: A fresh clone, for real — and the documentation

**This is the deliverable**, as phase 5's Task 8 was.

**Files:**
- Modify: `docs/plans/phase-6-install.md` ("What running it found")
- Modify: `CLAUDE.md` (Quick Start)
- Modify: `docs/plans/cross-platform-port.md` (the phase 6 row)
- Modify: `docs/plans/PICK-UP-HERE.md`

- [ ] **Step 1: A fresh clone, in its own directory**

Nothing else running JARVIS. Clone the branch somewhere with no venv and no
`node_modules`:

```bash
git clone --branch feat/phase-6-install D:/Repositories/jarvis D:/Repositories/jarvis-install-test
cd D:/Repositories/jarvis-install-test && py install.py
```

Record every step's line and the wall-clock time. Expected: all ten steps
pass; a `.env` is created; the voice downloads (63 MB) and whisper is found
already cached; preflight's verdict closes the run.

- [ ] **Step 2: Launch it from the Start menu, and talk to it (Ken)**

Expected: the window opens on the orb; JARVIS hears and answers.

- [ ] **Step 3: Run it again**

```bash
cd D:/Repositories/jarvis-install-test && time py install.py
```

Expected: every stamped step skipped; record the time (the spec's bar: seconds,
not minutes — Playwright's always-run step is the one to watch).

Then change one lockfile and confirm only that step reruns:

```bash
cd D:/Repositories/jarvis-install-test && echo "" >> electron/package-lock.json && py install.py && git checkout electron/package-lock.json
```

- [ ] **Step 4: Start with Windows, for real (Ken)**

Tick "Start with Windows", sign out and back in. Expected: no window, the
tray icon, the balloon, and JARVIS answers when spoken to. Untick it after.

- [ ] **Step 5: Point the shortcut back at the working checkout, and clean up**

The test clone rewrote `JARVIS.lnk`. From the working checkout:

```bash
py install.py
```

Then delete `D:/Repositories/jarvis-install-test`.

- [ ] **Step 6: Both gates**

```bash
.venv/Scripts/python -m pytest
cd electron && npm test
```

- [ ] **Step 7: Write down what happened**

- `docs/plans/phase-6-install.md`: a "What running it found" section — the
  timings, the EBUSY finding from Task 7, the registry entry from Task 10,
  anything that did NOT work.
- `CLAUDE.md` Quick Start: lead with

  ```markdown
  **On your own machine, one command does all of this:** `py install.py`
  (Windows) or `python3 install.py` (macOS, UNVERIFIED), from the checkout —
  and again after every `git pull`. It checks Python 3.11+, Node 22.12+ and
  npm, builds everything below, fetches the voice and the whisper model,
  creates `.env` if there is none (never edits one), adds a Start-menu entry,
  and ends with preflight. The steps below are what it does, for reference.
  ```

  and add `install.py` and `env_file.py` to Key Files.
- `docs/plans/cross-platform-port.md`: phase 6 **DONE on Windows** with the
  date and the PR; macOS UNVERIFIED.
- `docs/plans/PICK-UP-HERE.md`: phase 6 done; what the Mac run should report.

- [ ] **Step 8: Commit**

```bash
git add docs/plans/phase-6-install.md CLAUDE.md docs/plans/cross-platform-port.md docs/plans/PICK-UP-HERE.md
git commit -m "Phase 6: what installing from a fresh clone found"
```

---

## Self-review

**Spec coverage.** The ten steps in order: prerequisites (3), venv, packages,
Playwright (4), `.env` (5), models (6), frontend and Electron (7), shortcut
(8), preflight and `main` (9). Re-running and stamps: 4, 7, verified in 12.
`.env` never edited, parser moved: 2, 5. The shortcut and its environment-only
paths: 8. "Start with Windows", Windows-only, starting in the tray: 10, after
the spec's first risk is measured in 1. The `npm ci`-while-running risk: 7
Step 1. The registry risk: 10 Step 6. CI running Electron's tests: 11. The
live checks and documentation: 12. macOS: marked UNVERIFIED throughout; Ken
runs it there after the merge.

**Placeholders.** None: every code step carries its code. Two measured values
are named where they are unknown until measured — the npm busy code (Task 7
Step 1, with the expected value and what to do if different) and Task 1's
verdict (with the fallback written out).

**Type consistency.** `Context(root, env, python, version, tools)` from Task 3
is what every step takes; `Result(returncode, stdout, stderr)` with `.output`
is what `run` returns in every task and every `Recorder` reply;
`venv_python`, `_digest`, `_is_current`, `_stamp` (4) are used unchanged in
7; `effective_env` (5) in 6 and 9; `electron_exe` (7) in 8; the step names in
`STEPS` (9) match the test in 9 and the spec's order.
