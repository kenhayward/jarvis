# Phase 5: the Electron application

Taking JARVIS out of the browser. Written 2026-09-10, immediately after phase
4 closed.

Implementation plan: [`phase-5-electron-plan.md`](phase-5-electron-plan.md).
It opens with the hidden-window spike, because that is the one risk below
which can invalidate this document.

Companion documents: [`cross-platform-port.md`](cross-platform-port.md) for
why the phases are ordered as they are, and
[`phase-4-speech.md`](phase-4-speech.md), whose 4-zero spike already answered
several questions this phase would otherwise have had to ask.

## Two deliberate departures from the plan, stated first

**This is built Windows-first, and `cross-platform-port.md` says "macOS
first".** Decided 2026-09-10: the work is happening on the Windows box, and
4-zero already proved the renderer works there. The cost is real and is not
hidden — the one thing phase 5 already knew going in is a **macOS** fact (the
TCC gate), and it cannot be verified from here. Everything macOS-specific in
this document is written from documentation, which is exactly the condition
`jarvis_platform/windows/` was written under and which cost this port two
wrong premises. Treat those parts as claims.

**"Electron shell" is now an Electron APPLICATION.** The plan's one-line
description says shell; the decision taken was tray-resident, supervising its
own server. That is more than a shell and the difference is deliberate:

* the shell owns the Python server, because otherwise phase 6 (packaging and
  release) has nothing to package
* closing the window HIDES it and JARVIS keeps listening, because a voice
  assistant you must keep a window open for is an odd thing, and tray
  residency is far harder to retrofit than to build in

## What 4-zero already settled, so this phase does not re-ask

Measured 2026-09-10 in a real Electron renderer (44.3.0 / Chrome 152), on both
platforms. Full detail in [`phase-4-speech.md`](phase-4-speech.md).

* `webkitSpeechRecognition` is **defined and fails at runtime** with
  `error=network`. A feature check reports it working. This is why JARVIS
  needs `JARVIS_STT_BACKEND=whisper` under Electron, and why the shell should
  say so if it finds the browser backend configured.
* `getUserMedia` and Web Audio both work, given a permission handler.
* **Electron denies media unless the app installs
  `session.setPermissionRequestHandler`.** Without it `getUserMedia` fails in
  a way indistinguishable from the macOS TCC case below.
* **macOS has a second gate.** `setPermissionRequestHandler` is necessary but
  NOT sufficient: TCC moved `not-determined` -> `granted` only via
  `systemPreferences.askForMediaAccess('microphone')`, and a packaged app also
  needs `NSMicrophoneUsageDescription` in its `Info.plist`. Install the
  handler, still fail, and there is no way to tell which gate is shut.

## The design

### The renderer loads the server's own page

`http://127.0.0.1:8340/` — not a bundled copy of the frontend.

`server.py` already serves the whole application from one origin when
`frontend/dist` exists: `/` is `index.html`, `/dashboard` is the run monitor,
`/assets` is mounted. Vite is a development convenience, not part of the
product.

So there is exactly one frontend, served from one place, and Electron is a
viewer of it. A second bundled copy would be a second thing to keep in step —
and `tests/dashboard_page.py` has already shown what "the thing you run is not
the thing you test" costs: sixteen tests skipped in silence for months.

### HTTP, not HTTPS, and the certificates stop being required

`CLAUDE.md` currently calls the certs "NOT optional", and that is true of the
DEV-SERVER workflow for one reason: `frontend/vite.config.ts` hard-codes its
proxy target as `https://localhost:8340`.

There is no Vite here. `http://127.0.0.1` is a secure context by the same rule
that makes `localhost` one, so `getUserMedia` works over plain HTTP, and
`server.py` already serves HTTP when the certs are absent.

That removes the openssl step from the Electron path entirely. It does NOT
remove it from the dev-server workflow, which still needs them; both remain
true and the setup docs should say which is which.

### The server lifecycle

The one piece of real logic in the main process.

On launch, `GET /api/health` (it exists already, `server.py:2006`):

| what answers | what the shell does |
|---|---|
| a JARVIS | **attach**, and remember it did not start this one |
| nothing | spawn the server, poll health until ready, fail visibly on timeout |
| something that is not JARVIS | refuse, and say what it found |

**Attaching rather than starting a second** is the decision that matters, and
the reason is not politeness. Two servers means two brains on one Claude
subscription and two writers on one SQLite database; `run_store` is not built
for that and the second instance would be quietly wrong rather than loudly
broken. A developer with a dev server running is the normal case, not an edge
case.

**On quit, kill the server only if the shell started it.** Attaching to
somebody's dev server and then killing it on exit is a genuinely nasty
surprise, and the flag that prevents it is one boolean that must never be
guessed at.

**A server that dies mid-session is reported, not hidden.** The window says so
and offers to restart, rather than showing a blank page — which is the shape
of every failure this project has had to diagnose from the outside.

### Finding Python in development

`.venv/Scripts/python.exe` beside the repository, falling back to
`.venv/bin/python`.

Both names are tried rather than branching on the platform, which is the
lesson `tts.piper_bin()` learned on 2026-09-10: pip installs the console
script under a platform-specific name, testing only one finds nothing, and the
PATH fallback cannot rescue it because the venv is not activated. Same shape,
same fix, and it is written here so the third instance is not discovered the
same way.

Packaged builds are phase 6 and do not affect this.

### The tray

Closing the window hides it. The tray menu offers **Show** and **Quit**, and
Quit is the only way out — so it has to be findable. An application a person
cannot work out how to exit is worse than one that simply closes.

Because closing hides rather than exits, the server keeps running and JARVIS
keeps listening. That is the point of the decision.

### Permissions

`session.setPermissionRequestHandler` granting `media`, on every platform,
because 4-zero measured that Electron denies it otherwise.

On macOS, additionally `systemPreferences.askForMediaAccess('microphone')`
before the window loads, and `NSMicrophoneUsageDescription` in the packaged
`Info.plist`. **This cannot be verified from the Windows box.** It goes in as
code carrying a comment that says it is unverified — not as a claim that it
works.

### The STT backend under Electron

Electron has no speech service: `webkitSpeechRecognition` is present and fails
at runtime. So `JARVIS_STT_BACKEND=browser` — the default — means an Electron
JARVIS that appears to be listening and never returns a word.

The shell reads `/api/settings/status` and, if the backend is `browser`, says
so plainly in the window rather than letting the user discover it by talking
to something deaf. It does not silently change the setting: that is the user's
`.env`, and a program that rewrites configuration to suit itself is worse than
one that explains.

## What is out of scope

* **Packaging, code signing, installers, auto-update** — phase 6.
* **Bundling a Python runtime.** The shell finds an existing venv; making
  JARVIS installable without one is phase 6's problem and a large one.
* **Any change to the voice path.** Phase 4 closed; this phase moves the
  window the page lives in and nothing else.

## Testing

The main-process logic — the health probe, attach-versus-spawn, the
kill-only-if-we-started flag, Python discovery — is plain JavaScript with no
Electron in it, and is tested as such.

**The window itself needs a real run, and that is part of the work rather than
a caveat in the commit message.** Phase 4c shipped with "the page half has
never been run against a live JARVIS" written into its own commit, and ten
minutes of actually running it produced four defects, two of which no test
could reach. The same standard applies here: this phase is not done until
somebody has launched it, talked to it, closed it to the tray, and quit it.

## What would make this design wrong

Stated so it is falsifiable — and with the caveat phase 4 earned: **this list
can only contain failures already imagined, and the thing that overturned
phase 4 was on nobody's list.** Run the cheap experiment anyway.

* **`getUserMedia` fails in a packaged macOS build** despite the handler and
  `askForMediaAccess`. Then the microphone story on macOS needs solving before
  phase 6 can ship anything, and this document's macOS half is wrong.
* **Attaching to a running server proves unsafe** — for instance if the shell
  cannot reliably tell a JARVIS from something else on the port. Then refusing
  is the honest fallback, and the developer workflow gets worse.
* **Tray residency turns out to need a running window** for audio to keep
  working. Chromium throttles hidden windows aggressively, and if capture
  stops when the window is hidden, "closing hides and JARVIS keeps listening"
  is a promise the platform will not keep. **This is the most likely of the
  three and the cheapest to test — do it first.**

## Rules carried forward

* A measurement must go through the product's own path, or it measures
  something else. See `phase-4-speech.md`, "How the boundary moved three times
  in one day".
* Both names, every platform: a program name that needs a Windows extension
  has now cost this port three separate defects.
* The macOS suite is the gate, and it cannot be run from the Windows box.
* PRs to `kenhayward/jarvis` with the base passed explicitly.
