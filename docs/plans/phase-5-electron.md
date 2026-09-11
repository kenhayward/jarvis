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

**Absent was the catch** (found in Task 3, 2026-09-11). Any machine that has
run the dev workflow has the certs, and `server.py` then switches HTTPS on by
itself — a server the application started served TLS to its own `http://`
health poll. `server.py` gained `--no-ssl` (it already had `--ssl`; now it is
`--ssl`/`--no-ssl`, and neither still means "if the certs are there"), and
the application always passes it. That is the one change this phase makes to
`server.py`, and it was Ken's call over spawning `uvicorn server:app`, which
would have kept `server.py` untouched at the price of a second startup path.

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

## Task 1: does audio survive a hidden window? — MEASURED 2026-09-11

The spec's own risk list named this the most likely thing to be wrong and the
cheapest to test. It was wrong, and finding out how took five runs, one of
which reached the wrong conclusion and one of which corrected it. All five are
kept, because the mistake in the middle is the most useful part.

### The answer

**A hidden Electron window loses about a third of its captured audio, and
`webPreferences: { backgroundThrottling: false }` removes the sustained loss.**
Every run is ten minutes on the Windows box, 16 kHz capture, measured by the
audio thread's own running sample count against wall-clock time:

| run | window | captured | silent seconds |
|---|---|---|---|
| control | **visible** | **9,728,000 / 9,728,000 — 100.0%** | 0 |
| control | **hidden** (default throttling) | **6,528,000 / 9,728,000 — 67.1%** | 200 |
| fix | **hidden**, `backgroundThrottling: false` | **9,312,000 / 9,728,000 — 95.7%** | 26 |

The visible and hidden controls are the same probe, the same session, nothing
else holding the microphone — the only variable is the window being hidden,
and it costs exactly a third. The loss is not delayed audio that arrives
later: there is no catch-up, and in every run `captured` equalled `received`
to the sample, so the transport from the audio thread to the page is lossless.
What is lost is never captured at all.

**The throttling starts within about thirty seconds of hiding, not at
Chromium's five-minute mark.** That is why the first, 12-second test looked
clean: it ended before the throttling began. A short test of a long-running
condition cannot see the failure that matters.

**It affects `AudioWorklet` as well as `ScriptProcessorNode`.** Moving capture
off the main thread does not help; the whole renderer's audio is throttled.
So this is not a reason to move `capture.ts` to AudioWorklet — that is still
worth doing because ScriptProcessor is deprecated, but it is a separate change
and it does not fix this.

**How the fix works, verified rather than assumed.** With
`backgroundThrottling: false` the renderer is never told it is in the
background: `document.hidden` stays `false` throughout, and that is the
mechanism, not a sign the window failed to hide. The window's absence from
the desktop was checked independently — `win.hide()` was logged by the main
process, and the spike's window was absent from the visible top-level windows
enumerated by `jarvis_platform.windows.screen.windows()`. A result that says
"not hidden" is exactly the kind that has to be checked from outside.

### What is NOT established

The fixed run was not perfect. Minutes 0-6 and 9-10 held exactly 16,000
samples a second; **minutes 7 and 8 dipped to 13,559 and 11,661 and then
recovered**, giving the 26 silent seconds.

Its cause is unknown. It has the same fall-then-recover shape as run 3 below,
which was confounded by another process holding the microphone, and the
visible control had no dip at all — but one run cannot separate a transient on
the machine from something about a hidden, unthrottled window. The sustained
loss is gone; a short, recovering one is unexplained.

**If a tray-resident JARVIS ever drops words, measure this first** — and with
a visible control over the same ten minutes, because that is the only thing
that made any of these numbers interpretable.

### The five runs, including the wrong turn

1. **12 seconds hidden, Ken talking.** Frames steady at ~4/s, peak tracking
   his voice, and his own pause at 55-69s dropped the peak to the room floor —
   an unplanned control proving the peak followed speech. Looked clean. **Too
   short to see anything:** the throttling starts after about thirty seconds.

2. **Ten minutes hidden, ScriptProcessorNode.** Full rate for four minutes,
   then 2.53 callbacks/s — 65% — for the rest. Attributed at the time to
   main-thread throttling, since ScriptProcessor runs on the main thread.

3. **Ten minutes hidden, AudioWorklet.** Slowed to ~64% at 33s, and then
   **recovered to full at 366s while still hidden.** Hidden-page throttling
   does not lift while the page stays hidden, so this did not fit. The
   explanation offered for run 2 was **withdrawn** — reasonably, since the
   data contradicted it — and the proper control was proposed instead.

4. **The controls: visible, then hidden, back to back**, with the JARVIS
   server and Vite stopped and its browser tab closed so nothing else was
   capturing the microphone. Visible 100.0%, hidden 67.1%, **and the hidden
   run did not recover.** So hiding WAS the cause, the withdrawal in step 3 was
   the wrong call, and run 3's recovery was the confound: the JARVIS page,
   still open in Chrome with the local STT backend, had been holding the same
   USB microphone.

5. **Hidden, `backgroundThrottling: false`.** 95.7%.

The lesson is the one phase 4 already paid for, arriving from the other
direction: **a result you cannot explain is a reason to add a control, not to
pick a story.** Run 2 picked a story that happened to be right. Run 3 found a
fact that contradicted it and withdrew it, which was the right instinct and
the wrong conclusion — only a control that removed the competing consumer
could tell those apart. Neither the first explanation nor its withdrawal was
worth anything until step 4 existed.

A second lesson, smaller: **remove competing consumers before measuring.** The
live JARVIS session left running from earlier testing was capturing the same
microphone the spike measured, and it produced a result that looked like
evidence against the true cause.

## What running it found — 2026-09-11

Ken ran the application by hand on the Windows box — `npm start`, a real
conversation through the window, the tray — and reported that it **worked
well**. What follows is what the records show, and what they cannot.

### What the records show

The server logged to Ken's terminal, which was not captured, so the evidence
is the brain's own session transcripts (Claude Code writes them under
`~/.claude/projects/...-data-jarvis/`) and the process table afterwards.

- **Recognition through Electron works, and project names reach tools.**
  Whisper, fed by the page's own capture inside the Electron window, heard
  "Good morning. Is there anything happening in the jarvis project?" word for
  word; the brain called `list_sessions` with `filter: "jarvis"`, then
  `session_detail` on it, and answered correctly (the open PR, waiting on the
  voice test). A second question, "Any other projects running, Jarvis?", was
  heard and answered from `list_sessions`.
- **Quit leaves nothing behind.** After Ken quit from the tray: no Electron
  process, port 8340 free.
- Earlier in the day, by hand and against a silent stand-in: the X hides and
  the first-hide notice appears, a second launch reshows the window, tray
  Quit exits, and a server the app attached to survives it (Tasks 5 and 6).

### What the records cannot show

Barge-in, speaking while the window was hidden, the `mic: DEAF` line from
the first launch, and whether the recogniser warning stayed away — all of
those live in the terminal output. They rest on Ken's "worked well", which
is a person's report and not a measurement. If a tray-resident JARVIS ever
drops words, re-measure hidden capture first, with a visible control (see
Task 1).

### A defect the run exposed — not in the Electron code

**The brain rotated its context after ONE question.** The rotation budget
is 120,000 tokens of conversation; the first question's turn made four
model calls (thinking, two tool calls, the answer) of about 37,000 tokens of
context each. Ken's next words, straight after the rotation, were "I lost
it." — plausibly the rotation's pause, not confirmed.

Measured, not inferred: a `claude -p --output-format stream-json` turn with
two tool reads reported per-call contexts of 37,765 / 53,015 / 55,079 /
55,278 tokens, and its `result` event reported **201,137 — exactly their
sum.** `brain.py` sizes the context window from that `result` event
(`_Turn.context_tokens`), so every turn that uses tools counts the window
once per model call. The question above counted as about 147,700 tokens, less
a baseline of 12,048, against a real window of about 37,000.

The baseline is wrong too, and in the same direction: the warm-up's full
prompt was 36,744 tokens, but it arrived as 12,046 read from cache plus 24,696
written to it, and `context_tokens` excludes the written part — correct only
for a sum across calls. Per call, the prompt is all three columns; the next
call read exactly 36,742 from cache.

This is `brain.py`'s, predates phase 5, and is fixed separately: the window
is the LAST model call's prompt, not the turn's total.

### Gates

`cd electron && npm test`: 41 passed. `pytest`: 2585 passed, 4 failed in
`tests/test_specs_api.py`, failing identically on `main` — a real project on
this machine leaking into the specs list through `~/.claude`, raised
separately.

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
* ~~**Tray residency turns out to need a running window.**~~ **It did — and
  it is fixed by one line. Measured 2026-09-11, see "Task 1: does audio
  survive a hidden window?" below.** A hidden Electron window loses a third of
  its audio unless `webPreferences.backgroundThrottling` is `false`.

## Rules carried forward

* A measurement must go through the product's own path, or it measures
  something else. See `phase-4-speech.md`, "How the boundary moved three times
  in one day".
* Both names, every platform: a program name that needs a Windows extension
  has now cost this port three separate defects.
* The macOS suite is the gate, and it cannot be run from the Windows box.
* PRs to `kenhayward/jarvis` with the base passed explicitly.
