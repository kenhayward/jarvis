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
   hint — the winget or brew command that would install it — and nothing
   more. The script never runs an installer for you.
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
* Steps 2, 4 and 6 skip when their product already exists.
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

## What would make this design wrong

* **A window that has never been shown may not capture audio.** Phase 5's
  Task 1 measured a window shown and then hidden; starting hidden is a
  different state, and Chromium may not grant or run capture in it at all.
  **This is measured first**, the way phase 5 measured its own biggest risk
  first. If it fails, "tray-only at login" becomes "open the window, then hide
  it once the microphone is live" — a visible flash at login, and still
  listening.
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
