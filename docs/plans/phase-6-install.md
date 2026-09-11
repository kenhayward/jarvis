# Phase 6: installing JARVIS on your own machines

Designed 2026-09-11, on the Windows box, straight after phase 5 merged. The
plan that implements it is `phase-6-install-plan.md`, written after this is
reviewed.

## What the phase table said, and what was decided instead

`cross-platform-port.md` names phase 6 "Windows packaging and release" and
nothing more. Phase 5 left it two notes: packaging, signing, installers and
auto-update were deferred here, and "making JARVIS installable without [a
venv] is phase 6's problem and a large one."

Three decisions, taken by Ken in the design conversation, shrink that
considerably:

* **The audience is Ken's own machines.** Not other developers, not the
  public. So: no code signing, no auto-update, no guided setup for someone
  who has never used a terminal, and a SmartScreen warning would be fine. (In
  phase 5 none appeared: the one executable fetched, `electron.exe`, came
  through npm rather than a browser download.)
* **The git checkout IS the installation.** No bundled Python runtime, no
  Program Files, no installer. One command, `install.py`, turns a fresh
  checkout into a working JARVIS; updating is `git pull` and running it
  again. The standalone route — freezing faster-whisper and onnxruntime,
  moving every repo-relative path into a per-user layout — was the large job
  phase 5 warned about, and it buys nothing on a machine that already has
  the checkout.
* **One script for both machines.** It is cross-platform. Its macOS half is
  written from the Windows box and is UNVERIFIED until Ken runs it on the Mac,
  exactly as phase 5's macOS half was.

So "release" in this phase means: a machine Ken controls goes from `git
clone` to a JARVIS in the Start menu with one command, and stays current with
two.

## The script: `install.py`

At the repository root. Run with any Python 3.11 or newer — `py install.py`
on Windows, `python3 install.py` on macOS. Standard library only, because it
runs before the venv exists.

Every step checks before it acts and prints one line: done, skipped (already
current), or failed. **The first failure stops the script**, printing the
exact command that failed and the end of its output — a setup that carries on
past a failure leaves a checkout that looks installed and is not.

### The steps, in order

1. **Prerequisites — checked, never installed.** Python 3.11+ (the
   interpreter running the script), git, Node 22.12+ with npm, and a `claude`
   on PATH. The Node floor is Electron 44's own (`engines: >= 22.12.0`, and
   its downloader's); Vite accepts older. Each missing one is a one-line
   hint — the winget or brew command that would install it, chosen by which
   of the two this machine HAS — and nothing more. The script never runs an
   installer for you. Python, Node and npm stop the script; a missing git
   or `claude` is a note and it carries on, because nothing it installs
   needs either — git is for the next `git pull`, and Claude Code is judged
   properly by preflight at the end.
2. **The venv.** Create `.venv` from the running interpreter, or keep an
   existing one if its Python is 3.11+. Its interpreter is found under BOTH
   platform names (`.venv/Scripts/python.exe`, `.venv/bin/python`), as
   `electron/python.js` does — the port's rule, learned three times.
3. **Python packages.** `requirements.txt`, `requirements-piper.txt` and
   `requirements-stt.txt`. The voice and the ear are optional for a Chrome
   JARVIS; the Electron application is what this sets up, and it needs both.
4. **Playwright's Chromium** — `read_page` and `look_at_page` need it.
5. **`.env`** — see below. Before the models, because it names them.
6. **Models.** The piper voice into `data_paths.voices_dir()`, and the
   whisper model into the Hugging Face cache — whichever ones `.env` names
   (`JARVIS_PIPER_VOICE`, `JARVIS_STT_MODEL`), defaulting to
   `en_GB-alan-medium` (63 MB) and `base.en` (141 MB). "Present" is decided by
   the functions JARVIS itself uses — `tts.piper_model_path`,
   `stt.model_is_cached` — run through the venv, so "installed" means what
   the server will find, not what the script believes.
7. **The frontend.** `npm ci` and `npm run build`: the application loads the
   page the server serves out of `frontend/dist`.
8. **Electron.** `npm ci` in `electron/`, then `node
   node_modules/electron/install.js` — the unpack step `npm` alone does not
   do (found in phase 5).
9. **The Start-menu entry** (Windows) — see below. On macOS the script prints
   the launch command instead; a Mac `.app` is out of scope.
10. **Preflight.** `preflight.run_checks()` through the venv, every result
    printed. Claude Code — installed, new enough (2.1.224), logged in — is
    reported here, never automated: logging in is Ken's.

### Running it again

After a `git pull`, run it again. It must be fast when nothing changed, or
nobody will.

* Steps 3, 7 and 8 record a hash of their inputs — the requirements files,
  the lockfile — in a stamp **inside the thing they built** (`.venv/`,
  `node_modules/`), and skip when it matches. Delete the venv and the stamp
  goes with it, so the next run reinstalls rather than trusting a stamp for
  something that is gone.
* Steps 2 and 6 skip when their product already exists. Step 4 always runs:
  Playwright's own `install chromium` skips a browser it already has, which
  is simpler and more reliable than this script guessing where Playwright
  keeps them (it moves with `PLAYWRIGHT_BROWSERS_PATH`). The fresh-clone run
  times it to hold that to account.
* The frontend BUILD always runs: a pull can change `frontend/src` without
  touching the lockfile, and the build takes seconds.

## `.env`

`server.py`'s `_parse_env_lines` is marked as the one definition of what a
line of `.env` is. It became one after three copies disagreed and a gap let a
POSTed value redirect the `claude` binary the brain is spawned from. The
script must not make a fourth copy — and cannot import `server.py`, whose
imports need the venv's packages.

* **The parser moves, unchanged, into `env_file.py`** — standard library
  only. `server.py` imports it under its existing name, so its callers and
  tests are untouched, and `install.py` imports the same function.
* **Which file:** `JARVIS_ENV_FILE` if set, else the repository's `.env` —
  the server's own rule.
* **No `.env` yet:** create it from `.env.example`, then a short labelled
  block with what the application needs on this machine:
  `JARVIS_STT_BACKEND=whisper` (Electron has no speech service; the default
  `browser` recogniser is deaf there — measured in 4-zero), and
  `JARVIS_TTS_BACKEND=piper` **only if there is no `say` on this machine** —
  asked of the machine, not of the operating system, per the repository's
  rule. It prints what it wrote. Creating a file on request is not editing
  someone's configuration.
* **An existing `.env` is never modified.** It is read, and every setting that
  would leave the application deaf or mute here is reported with the exact
  line that fixes it: an unset or `browser` recogniser ("the application will
  hear nothing"), a `say` voice where there is no `say` ("JARVIS will not
  speak"). Phase 5's rule, kept: a program that rewrites configuration behind
  you is harder to trust than one that explains.

## The Start-menu entry

`install.py` creates `JARVIS.lnk` in the user's Start-menu Programs folder,
launching this checkout's `electron.exe` with the `electron/` directory as its
argument — what `npm start` runs, without the terminal.

* Its icon is `electron/jarvis.ico`, made from the tray ring and committed —
  not Electron's own logo.
* It is created through PowerShell's `WScript.Shell`, and **the paths reach
  PowerShell only as environment variables, never spliced into the script's
  text.** That is phase 3's launcher lesson — a shell that re-parses a path
  will eventually meet one it breaks on — applied before it is needed rather
  than after.
* Running `install.py` again rewrites it, so a moved checkout is mended the
  same way it was installed.
* Launched while JARVIS is already running, it shows the running one: phase
  5's single-instance lock.

## Starting with Windows

A **"Start with Windows"** checkbox in the tray menu, **off by default**,
through Electron's `app.setLoginItemSettings`. On Windows that is a `Run`
entry in the user's registry hive, naming this checkout's `electron.exe` and
the application's directory; the checkbox reflects what Windows reports back,
not what the application last wrote.

* **Started at login, JARVIS starts in the tray, without a window,** and says
  so once with the same silent notice phase 5 shows on the first hide:
  "JARVIS started with Windows and is listening." It knows how it was
  launched from a `--hidden` argument carried in that registry entry.
* **The checkbox exists only where it works.** On macOS an unpackaged
  Electron app cannot give its login item the argument that names our
  application, so a checkbox there would do nothing — and a platform that
  cannot do something withdraws it rather than faking it.
* The login-item decisions (the entry's arguments, whether this launch came
  from login) live in `electron/login.js`, with no Electron import and tested
  with `node:test`, beside `server.js` and `policy.js`. `main.js` wires them.

## Task 1: does a never-shown window capture audio? — MEASURED 2026-09-11

**Yes, as well as a visible one, and with no user gesture.** A throwaway
Electron 44.3.0 app created its window with `show: false` and
`backgroundThrottling: false` — exactly what `main.js` will do at login — and
loaded a page that, like `frontend/src/main.ts`, started capture on its own a
second after load: `getUserMedia({audio: true})` into a 16 kHz `AudioContext`
and a `ScriptProcessorNode`, as `capture.ts` does, with a second context
standing in for playback. Nothing was ever clicked. Captured samples counted
against wall-clock time, nothing else holding the microphone:

| run | window | microphone | audio contexts, no gesture | captured |
|---|---|---|---|---|
| control, 5 min | shown | granted | both `running` | 4,796,416 / 4,800,008 — **99.9%** |
| case, 5 min | never shown | granted | both `running` | 4,796,416 / 4,800,002 — **99.9%** |
| check, 1 min | never shown | granted | both `running` | 958,464 / 960,024 — **99.8%** |

The never-shown run is indistinguishable from the control at every ten-second
mark — no dip, no decay — and better than phase 5's shown-then-hidden window
(95.7%, with an unexplained two-minute dip). Nobody has to click the page for
either context to run: Electron's default autoplay policy does not require
one.

**Checked from outside, not taken from Electron's word.** The page reports
`document.visibilityState === "visible"` throughout — the mechanism of
`backgroundThrottling: false`, which phase 5 also saw, not a sign the window
showed. So during the one-minute check the desktop's visible top-level windows
were enumerated with `jarvis_platform.windows.screen.windows()`: twelve, none
of them the spike's, while its four Electron processes ran.

**Verdict: Task 10 keeps the design** — at login the window is created with
`show: false` and never flashed. The fallback is not needed.

## What running it found — 2026-09-11

### A fresh clone, for real

`git clone --branch feat/phase-6-install` into `D:\Repositories\jarvis-install-test`
— no venv, no `node_modules`, no voices, no `.env` — then `py install.py`:
**all ten steps, exit 0, in 43 seconds.** That figure is flattered by warm
caches on this box (pip's, npm's, Electron's download, and the whisper model
in the Hugging Face cache); a genuinely new machine spends minutes more,
downloading. What it did: a `.venv` on **Python 3.14.6** — `py` answers 3.14
here, and every package, CTranslate2 and onnxruntime included, installed
cleanly, so the worry noted in Task 3 did not materialise — a `.env` created
with whisper and piper (no `say` here), the piper voice downloaded, both npm
trees installed, the Electron binary unpacked, the shortcut written, and
preflight's verdict.

**Updating** — `git pull` and run it again — took **3 seconds** with nothing to
do. **Changing one lockfile** (a blank line appended to Electron's) re-ran
exactly that step, `npm ci` and the unpack, in 6s; restoring it re-ran it once
more, as the changed hash says it must; a third run skipped everything in 3s.
Python packages were skipped throughout.

### Ken, talking to it

Launched from the Start menu — the ring icon — it was the clone's own
`electron.exe` and the clone's own venv running `server.py --no-ssl`, checked
in the process table. Its brain heard "What sessions do we have open,
jarvis?", listed six, then went into the Trypthos session on request and
answered "is anything waiting for me?". **It worked.**

**Four things no test could reach, all fixed the same day and confirmed by
Ken on the clone** (each fix pulled into it with `git pull` and a re-run —
the update path, exercised for real):

1. **The title bar showed Electron's icon.** The taskbar takes the shortcut's;
   the window needs its own — `icon: jarvis.ico`.
2. **Electron's default menu bar** (File/Edit/View, reload and DevTools on it)
   showed in the window — `removeMenu()` on each window.
3. **There was no way to reach the dashboard**: in Chrome you type
   `/dashboard`; the app has no address bar. The tray gained **Dashboard**,
   opening it in a window of its own so the orb never stops listening.
4. **Notices were titled "Electron".** Windows names a toast's source by the
   process's AppUserModelID; it is now `JARVIS`, and the taskbar icon stayed
   the ring.

### Found on the way, recorded in the plan task by task

- `npm ci` while JARVIS runs fails with **`EPERM`** (`unlink`, `errno -4048`)
  on a DLL in Electron's `dist`, after deleting what it could.
- `.env`'s **first occurrence wins**, so the block `install.py` appends could be
  silently overridden by a live line in `.env.example`; the created file is
  judged as the server reads it.
- Electron's login entry is named **`electron.app.Electron`** by default —
  shared by every unpackaged Electron app — and
  **`getLoginItemSettings().openAtLogin` is true for any entry with the same
  command**, even after ours was removed. The entry is named `JARVIS`; the
  checkbox reads the named list.
- A checkout path like `Ken's $HOME & 100% (copy)` round-trips through the
  shortcut exactly.

### Heard but not chased

Whisper transcribed two phantom utterances in the live run — "Beep. Beep.
Beep. Beep." and "T-shirt, t-shirt, t-shirt…" — hallucinations on background
noise; JARVIS answered both as not requests. A speech-recognition matter
(phase 4's territory), not an installation one.

### Not done yet

- **Start with Windows, for real** — tick it, sign out and in — and the
  spoken check of a JARVIS started hidden. The checkbox, the Run entry and
  the hidden start are verified; a real login is not.
- **The Mac.** Everything macOS-shaped in `install.py` (no Start menu, so it
  prints the launch command; `.venv/bin/python`; brew hints) is UNVERIFIED.

## What would make this design wrong

* ~~**A window that has never been shown may not capture audio.**~~
  **It does — measured, see "Task 1" above: 99.9% against a visible
  control's 99.9%, with no gesture.**
* **`setLoginItemSettings` for an unpackaged app on Windows** is documented to
  take a path and arguments. It is written from that documentation and must
  be checked by reading the registry after ticking the box, then by actually
  signing out and in.
* **`npm ci` on a checkout whose `node_modules` is in use** (a running
  JARVIS holds `electron.exe` open) may fail to delete it on Windows. The
  script should say "quit JARVIS first" rather than leave a half-deleted tree;
  whether that is a check or a caught failure is the plan's call, after
  seeing how it actually fails.

## Out of scope

* Installing Python, Node, git or Claude Code — hints only.
* Code signing, auto-update, a bundled runtime, an installer, Program Files.
* A macOS `.app` or login item.
* An uninstaller. Untick the checkbox and delete the shortcut; the checkout
  and its venv go with the folder.
* The dev-server certificates. The application does not need them (phase 5,
  `--no-ssl`); `CLAUDE.md` keeps them for the Vite workflow.

## Testing

**`install.py`, in pytest, on both CI platforms.** Every external command
goes through one function that the tests replace with a recorder, so nothing
is installed and every step's decision is checked: a missing prerequisite
stops with its hint; an existing venv is kept and a too-old one refused; an
unchanged hash skips and a changed one reruns; a fresh `.env` gets the right
block with and without `say`; an existing `.env` is byte-identical afterwards
with its problems reported; the models asked for are the ones `.env` names;
the shortcut's paths reach PowerShell only through its environment, whatever
characters they hold; a failure prints its command and output and stops.

`server._parse_env_lines` is tested to BE `env_file`'s function, not an equal
copy — the one-definition rule, pinned.

**`electron/login.js`, in `node:test`** — and CI starts running `cd electron
&& npm test`. Phase 5's 41 tests have so far run only when somebody
remembered to.

**Live, and this is the deliverable:**

1. The never-shown-window spike, first.
2. A fresh clone on the Windows box, in a directory with no venv and no
   `node_modules`: `py install.py`, launch from the Start menu, talk to it.
3. Run it again: everything skipped, timed. Change a lockfile: only that step
   reruns.
4. Tick "Start with Windows", sign out and in: JARVIS in the tray, listening.
   Ken's hand check.
5. The Mac: Ken runs it and reports. Until then the macOS half is UNVERIFIED.

## Documentation

`CLAUDE.md`'s Quick Start leads with `py install.py` / `python3 install.py`;
the manual steps stay beneath it as the reference for what the script does.
`cross-platform-port.md` records phase 6 as redefined and then done;
`PICK-UP-HERE.md` is updated at the end.
