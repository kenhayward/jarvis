# Cross-platform port: the phased plan

Taking JARVIS from a macOS-only assistant to one that runs on Windows too,
sequenced so every phase lands on its own and nothing is load-bearing until
the thing before it works.

Companion documents: [`windows-handoff.md`](windows-handoff.md), the live
working reference while the work spans two machines, and
[`phase-4-speech.md`](phase-4-speech.md), which is the design this document
kept referring to as 4b/4c/4d without ever writing down.

| # | Phase | Runs on | Status |
|---|-------|---------|--------|
| 0 | Spikes — measure, decide, no production code | Mac + Windows | partly done, the Windows half outstanding |
| 1 | Portability hygiene + a failing Windows CI job | Mac | **merged** (PR #3) |
| 2 | The platform layer, macOS only | Mac | **merged** (PR #4) |
| 3 | `jarvis_platform/windows/` — first Windows build | Windows | **code complete** 2026-09-09; CI gate deferred to after phase 4 |
| 4 | [The speech sidecar](phase-4-speech.md) | Mac, verified on Windows | **designed**, premise verified 2026-09-10; 4a next |
| 5 | Electron shell, macOS first | Mac | not started — but see the TCC note below, learned in 4-zero |
| 6 | Windows packaging and release | Windows | not started |
| 7 | Optional: container / remote speech sidecar | either | not started |

## Why this order

Windows comes before Electron so there is a working Windows build at phase 3
— in Chrome, with Web Speech, no sidecar and no Electron. Everything after
that improves both platforms at once rather than macOS alone for a month.

The alternative was the sidecar first, because it pays for itself on macOS
immediately: it retires the echo heuristics in `speech.py` and takes Google
off the voice path. Swap 3 and 4 if the Mac experience matters more than a
Windows build; nothing else moves.

## The blocker phase 4 exists to resolve

JARVIS has no server-side speech recognition. `frontend/src/voice.ts` runs
Chrome's `webkitSpeechRecognition` in the page and sends the resulting *text*
over the WebSocket; audio only ever travels the other way. Chromium's speech
service is a Google web service reached with keys only Google's own builds
carry, so **wrapping the existing page in Electron deletes the microphone**.
**Measured and confirmed 2026-09-10** (Electron 44.3.0 / Chrome 152) — though
not in the shape you would guess: the API is DEFINED there and fails at
runtime with `error=network`, so a feature check reports it working. See
[`phase-4-speech.md`](phase-4-speech.md).

Moving speech recognition to the backend is therefore a precondition for
Electron — and it is worth doing for its own sake. A large amount of
`speech.py` exists only because the server never hears anything:
`_echo_share`, `_is_stem_echo`, `ECHO_SHARE_WHILE_AUDIBLE`,
`SHORT_ECHO_GRACE_SEC` and a four-character stem rule are all text heuristics
standing in for a signal. With the audio server-side, the server also knows
exactly which samples it sent to the speaker and when, which is the reference
signal for acoustic echo cancellation.

## One thing phase 5 already knows, from phase 4's spike

`4-zero` wrapped the page in Electron to test phase 4's premise and found
something that belongs to phase 5 instead. Recorded here so it is not
rediscovered the hard way.

**On macOS, `session.setPermissionRequestHandler` is necessary but not
sufficient.** There is a second gate Windows does not have: TCC. Measured
2026-09-10 — status went `not-determined` → `granted` only via
`systemPreferences.askForMediaAccess('microphone')`.

So a packaged macOS Electron app needs **`NSMicrophoneUsageDescription` in
its `Info.plist`** and must **call `askForMediaAccess`**, or `getUserMedia`
fails. It fails looking exactly like the missing-handler case, which means
you can install the handler, still fail, and have no way to tell which gate
is shut. Both, or neither works.

Full detail, and the other two traps, in
[`phase-4-speech.md`](phase-4-speech.md).

## Six rules that hold across every phase

1. **The macOS suite passes at every commit.** Everything else here is
   negotiable; a red main is not, because it is the only thing between a
   refactor and a silent regression.
2. **No phase changes macOS behaviour** except 4b/4c/4d, where that *is* the
   deliverable. A port is not the moment to improve something else.
3. **Withdraw, never fake.** A platform that cannot do something removes the
   tool so the brain never sees it. A tool that always answers "not supported
   on Windows" costs ~250 tokens of schema every turn and invites an attempt.
4. **Argv, not strings.** Every new subprocess takes an argument list.
   PowerShell is a more forgiving injection target than AppleScript, not a
   less one.
5. **Dependencies argue for themselves** in their commit message, per
   CLAUDE.md.
6. **Every PR to `kenhayward/jarvis`** with the base passed explicitly, and
   the frontend gate (`npx tsc --noEmit && npm run build`) run on anything
   touching `frontend/`.

## Phase 3 — what is left

**Nothing on the Windows machine.** Both remaining items were answered by
measurement on 2026-09-09, and the one thing still outstanding —
`continue-on-error` on the Windows CI job — is **deferred on purpose** until
after phase 4, when there is a complete stable Windows build. The rest of this
section is the record of how the items were answered;
`docs/plans/windows-handoff.md` is the live document.

Both of the last two items were "verify a guess" tasks, and **both guesses
were wrong in the same direction**: a belief about Windows that had never been
measured, carried in a docstring, and relied on by code and by a test that
passed without testing it. That is the phase 3 lesson, more than any
individual fix.

Answered:

- ~~**The terminal launcher.**~~ **ANSWERED AND FIXED 2026-09-09.**
  `_terminal_argv`'s `wt` branch was correct as written — verified opening at
  a directory with a space in it, across a drive change. Its cmd.exe fallback
  had never been run and did not work: the composed `cd /d "<dir>" && <cmd>`
  went into one argv element, Python escaped the quotes as `\"`, and cmd.exe
  reads that literally. Beneath it, `cmd.exe` through `_spawn`'s pipes was
  headless, so there was no window either. The directory now travels as the
  spawn's `cwd` on both branches, which retires the `cd /d` question rather
  than answering it.

- ~~**Spawning `claude.cmd`.**~~ **ANSWERED AND FIXED 2026-09-09, and the
  premise was wrong.** `create_subprocess_exec` **can** run a `.cmd` —
  measured, rc 0 — because Windows reaches a batch file through the command
  processor implicitly. No spawn wrapper was ever needed.

  The real defect is that the implicit route re-parses the ARGUMENTS: a
  newline truncates one and `%NAME%` is expanded. `run_executor.py` was never
  exposed (simple argv, prompt over stdin — a real run through the npm shim
  succeeded untouched). `brain.py` was: its multi-line `--append-system-prompt`
  lost **60% of the system prompt**, silently, on any npm install.

  The predicted cure — `cmd.exe /c` at the call sites — was measured and
  damages the argument identically. The actual cure is to keep multi-line text
  out of argv entirely: the prompt goes to a file
  (`--append-system-prompt-file`, accepted as far back as the 2.1.224 floor),
  and `preflight`'s `claude_shim` check WARNs when `claude` is a batch shim.

  The lesson generalises past this item: **the task had been scoped for months
  from a belief nobody had measured**, and measuring changed both the
  diagnosis and the fix. This plan's own instruction — "verify it by
  installing the npm shim and spawning it, not by reasoning about it" — is
  what caught it.

- ~~**Session steering.**~~ **BUILT.** `socket.AF_UNIX` is not exposed by
  CPython on Windows, and Claude Code there publishes a NAMED PIPE in the
  same `messagingSocketPath` field. `session_steer` writes its one JSON line
  to it with the ordinary file API. Verified against a live session.
- ~~**`answer_dialog`.**~~ **WRITTEN OFF, permanently**, which is the answer
  this plan already allowed for. `Dialogs.terminal_of` cannot return anything
  as exact as a tty: measured, thirteen `claude.exe` processes against ONE
  owning pid across four window handles, because a window's owner is the
  terminal HOST and not the session inside it. Aiming a synthetic keystroke
  by focus instead is the one thing `base.Dialogs` forbids outright.
- ~~**Screen capture and the window list.**~~ **BOTH BUILT**, and split
  apart on the way, because only one of them ever had a rail to lose.
  Enumerating windows needs no permission on Windows. The pixels waited for
  a consent model and got one: `JARVIS_SCREEN_CAPTURE`, shipped OFF, read at
  call time — the one property of TCC worth reproducing, which is a switch
  the user turns on and can turn off again.
- ~~**The tool token, the launcher, notifications.**~~ Written from
  documentation in phase 3 and since **verified on a real box**, with one
  correction each. See the handoff's guess table.

## What to cut if it slips, in order

1. **Phase 7, the container.** Costs nothing to skip; the protocol exists
   either way.
2. **Phase 4d, echo cancellation.** The existing text heuristics are ugly but
   tuned, and nothing downstream depends on removing them.
3. **`answer_dialog` on Windows.** See above.
4. **Reading the active browser tab.** No clean Windows equivalent, low
   value. Already declared absent — the macOS `get_chrome_tab_info` was
   deleted in phase 2 rather than carried forward unused.
5. **Local speech recognition, if the accuracy bake-off disappoints.** Keep
   `browser` as the default STT backend and document Chrome as a requirement
   for voice. Everything else in the plan survives this.

Not on that list: phases 1 and 2. The defects were real bugs, and the
platform layer is what makes a second implementation maintainable rather than
a fork that drifts.
