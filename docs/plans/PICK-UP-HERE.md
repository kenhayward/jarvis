# Pick up here

Paste the block below into a fresh Claude Code session in this repository.
Everything in it is checkable against the repo — if a claim here disagrees
with the code, trust the code and fix this file.

Last updated 2026-09-11, at the end of the Windows session that built phase 5
— the Electron application — and merged it (PR #41). Before that, 2026-09-09,
the session that closed phase 3's last two items, `claude.cmd` and the
terminal launcher: both "verify a guess" tasks, both guesses wrong in the same
direction. Phase 5 went the same way — nearly every task's plan was wrong
somewhere, and each time measuring found it before building on it.

---

```
We're finishing the macOS→Windows port of JARVIS. Read
docs/plans/windows-handoff.md first — the "Picking this up on another
machine" and "What is left" sections at the top — then
docs/plans/cross-platform-port.md for why the phases are ordered as they
are. CLAUDE.md is the standing guidance for the repo.

Where things stand: PHASE 3'S CODE IS DONE. Windows runs the same suite
green on a real box (2542 passed, 60 skipped) and withdraws exactly one
tool (answer_dialog, permanently and by decision). The platform layer
(jarvis_platform/) is the only place that knows what a machine can do.

The last code item — spawning claude.cmd — was verified and fixed on
2026-09-09, and it is worth knowing HOW it was wrong, because the same
shape will recur. The premise carried since phase 1 was that
create_subprocess_exec cannot run a .cmd. It can; Windows routes a batch
file through the command processor implicitly. What that route really
does is re-parse the ARGUMENTS — a newline truncates one, %NAME% is
expanded — so brain.py's multi-line --append-system-prompt was losing 60%
of the system prompt on any npm install, silently, while run_executor.py
(simple argv, prompt over stdin) was never exposed at all. The predicted
fix, cmd.exe /c at the call sites, damages the argument identically. The
prompt now travels as a file. Nobody had measured any of it.

The launcher was the same story, found the same way. _terminal_argv's wt
branch was correct as written, and its cmd.exe fallback had NEVER worked:
it composed `cd /d "<dir>" && <cmd>` into one argv element, and Python
escapes those quotes as \" — CommandLineToArgvW's convention, not
cmd.exe's, which has no escape character inside quotes. The function's own
docstring said so four lines above the code that relied on it. cd failed,
&& short-circuited, the command never ran, and _spawn reported success.
Underneath that, cmd.exe spawned through _spawn's pipes was headless, so
the user got no window either. Both fixed; both verified on the box.

NOTHING is left on this machine. The one open item is deliberate: the
Windows CI job keeps continue-on-error until after phase 4, when there is
a complete stable Windows build. That is a decision (2026-09-09), taken
because an honest amber gate keeps iteration fast while the port is still
moving. DO NOT remove it as a tidy-up. When the time comes, check the JOB
and not the run's conclusion — a green tick can hold a red Windows leg
inside it.

PHASE 4 IS DONE (2026-09-10) — JARVIS hears you with no Chrome involved,
through faster-whisper base.en, and speaks through piper. Read
docs/plans/phase-4-speech.md if you touch the voice path.

PHASE 5 IS DONE ON WINDOWS (2026-09-11, PR #41) — JARVIS is a desktop
application: electron/ is a tray-resident Electron shell that starts and
supervises server.py and loads the page the server serves over plain
http://127.0.0.1:8340. Run it with `cd electron && npm install && node
node_modules/electron/install.js && npm start`. Ken ran it by hand and
talked to it; it worked. The spec is docs/plans/phase-5-electron.md —
read "What running it found" — and phase-5-electron-plan.md records, task
by task, where the plan was wrong and what measuring found instead.
CLAUDE.md's Key Files entry for electron/ carries the reasons behind the
parts most likely to be "simplified" by someone who was not there.

The findings that change how you would build anything near it:
- A HIDDEN Electron window loses a third of its captured audio (visible
  100.0%, hidden 67.1%, over ten minutes) unless
  webPreferences.backgroundThrottling is false (95.7%). Throttling starts
  ~30s after hiding — a short test cannot see it — and hits AudioWorklet
  too. A two-minute transient dip in the fixed run is UNEXPLAINED; if a
  tray JARVIS ever drops words, re-measure that first, with a visible
  control.
- server.py switches ITSELF to HTTPS whenever cert.pem/key.pem are beside
  it, and every dev box has them. The app spawns `server.py --no-ssl` — the
  one change phase 5 made to server.py.
- A JARVIS on HTTPS fails an http:// probe with UND_ERR_SOCKET, not
  ECONNREFUSED. Only a refused connection means "nothing is there";
  anything else means something holds the port, and the app refuses rather
  than start a second server over it.
- On Windows, killing the venv's python.exe (a redirector whose child is
  the real interpreter) takes the whole tree — interpreter, brain, the
  brain's MCP child — and so does the parent simply exiting. Measured; the
  macOS equivalent is not.

What is NOT verified: every macOS part of it (the TCC prompt, kill
behaviour, the tray; the first-hide notice is Windows-only), and barge-in
and hidden-window speech rest on Ken's "it worked" rather than a recorded
measurement. See "If you are on the Mac" below.

OPEN: PR #42 — the live run exposed that brain.py rotated its context after
ONE question. A stream-json `result` event reports usage SUMMED over the
turn's model calls, and the brain sized its window from it, so a turn with
tools counted the window once per call. Measured, fixed, tested there; not
merged as of this writing. Once it is, rotation comes at 120k of ACTUAL
conversation — much later than before — and JARVIS_BRAIN_CONTEXT_BUDGET is
the lever if that is too far.

Next in the phase table: phase 6, Windows packaging and release.

Also due: phase 3's continue-on-error deferral. It was "after phase 4", and
phase 4 is done. It is blocked on issue #36 — the Windows speech-chain
flakes. test_low_items_are_batched_into_one_utterance has now flaked three
times (the latest on PR #41, where the other Windows run of the same commit
passed).

If you touch the voice path, read "How the boundary moved three times in one
day" in docs/plans/phase-4-speech.md before anything else in it. The audio
boundary went segments -> streaming -> segments in a single day, and the
round trip is the most useful thing in the repo right now.

The short version: 4b measured barge-in with a raw microphone tap
(sounddevice) and found every engine transcribing JARVIS instead of the
user. That looked decisive and it reversed the design. It was wrong — the
product captures through getUserMedia, which applies echo cancellation
before anything sees a sample, and `{audio: true}` grants it (verified,
Chrome 152). Re-run through the browser, the same test transcribes the user.

The rule out of it, which is NOT "measure more" — 4b did measure, carefully:
A MEASUREMENT MUST GO THROUGH THE PRODUCT'S OWN PATH OR IT MEASURES
SOMETHING ELSE. Nothing in the result could reveal the difference; the
recordings were real, the levels good, the guards passed, the numbers
wrong.

4-zero, the spike it opens with, is DONE on both platforms (2026-09-10).
The premise holds: Electron deletes transcription and leaves the microphone
and Web Audio intact. But note HOW it is true — webkitSpeechRecognition is
DEFINED there and fails at runtime with error=network, so the obvious
feature check reports everything fine. Never feature-detect this.

Three traps came out of that spike and they are written up in
phase-4-speech.md. The one that matters beyond phase 4: on macOS,
setPermissionRequestHandler is NOT sufficient — TCC is a second gate needing
NSMicrophoneUsageDescription and askForMediaAccess, and it fails looking
exactly like the first one. Phase 5 will hit that.

Some ground rules this port has been run under, which matter more than usual
here:
- jarvis_platform/windows/ was written from documentation and is being
  corrected by measurement. Measure on the real machine before writing a
  comment as fact. This has now cost real work twice: a wrong diagnosis in
  a commit message (PR #20 vs #24 — the DACL story in the handoff), and a
  task scoped for months against a premise that was simply untrue (the
  claude.cmd item above).
- Declare a capability in the same commit as its implementation, never
  before. A capability says what is BUILT; whether JARVIS may use it today
  is a separate runtime question its module answers.
- A platform that cannot do something withdraws the tool; it never fakes it.
- Tests that dispatch through server must substitute the HOST
  (jarvis_platform.fake.fake_host), never patch jarvis_platform.macos.* by
  name. That mistake has been made three times in this repo and hides until
  the suite runs off macOS.
- Beware tests that pass without testing anything. Two were found in one
  day. `"--append-system-prompt" in joined` kept passing after the flag
  became --append-system-prompt-file, because the new flag contains the old
  one as a prefix. And the launcher's fallback test asserted that a
  composed shell line was built correctly — it was, and it had never
  worked. Pin the RULE, not the string: "no argv element contains a
  newline", "no argv element contains a quote". Phase 5 added two more:
  the supervisor's tests passed with a carriage return in the middle of
  their Windows paths (a shell collapsed "C:\\repo" to "C:\repo"), because
  they compared the mangled constant with itself; and the fake `claude`
  reported every turn as a single model call, so no test could see the
  brain counting its window four times over. A fake has to behave like what
  it stands in for — measure the real thing, then make the fake match.
- Run the full suite (bare `pytest`, no flags) before pushing, and the
  frontend gates (cd frontend && npx tsc --noEmit && npm run build) if you
  touch frontend/. If you touch electron/, run `cd electron && npm test` —
  CI does not run it.
- PRs go to kenhayward/jarvis: gh pr create --repo kenhayward/jarvis --base main
```

---

## If you are on the Mac

The macOS suite is the gate and cannot be run from the Windows box. Several
merged PRs changed shared surfaces (`session_watch.inbox_exists` / `is_pipe`,
`Secrets.restrict`, `Screen.CAPTURE_GATE`, `tests/conftest.py` rails), and the
`claude.cmd` fix changes `brain.py` on BOTH platforms — the launch prompt now
travels as a file rather than in argv, so the macOS leg is doing real work on
it. The first useful thing on a Mac is simply:

```bash
pytest
```

and reporting the number. The last figure recorded here for macOS is 2523
passed / 2 failed, from *before* any of this work — it is stale, and nobody
has re-run it since.

The second useful thing is **phase 5 on a Mac**, because every macOS line of
`electron/` was written on the Windows box and is marked UNVERIFIED:

```bash
cd electron && npm install && node node_modules/electron/install.js && npm start
```

Worth reporting: whether the microphone works first time or macOS's TCC
prompt appears (`main.js` calls `askForMediaAccess`; a packaged build will
also need `NSMicrophoneUsageDescription`, which a dev `npm start` does not
exercise); whether Quit from the tray takes the brain with it (on Windows the
whole tree dies; on macOS `kill()` is a SIGTERM to the interpreter, and
nobody has looked); and whether Cmd+Q quits rather than hiding (the fix for
that is in, and untested there).

## Setting up a fresh Windows box

Two corrections to the handoff's setup section, from doing it again on
2026-09-09:

- **`py -3.12` may not resolve at all.** On this box `py` answers 3.14 and
  PATH answers 3.13; there is no 3.12. Build the venv from an absolute
  path — `C:\Program Files\Python313\python.exe` — and 3.13 runs the suite
  clean.
- **A local Windows run is short unless you set the box up for it.** Two
  separate gaps, both found by quoting numbers that were wrong:
  `tests/test_dashboard_page.py` skips in full without `frontend/node_modules`
  and chromium (16 tests), and 14 CONTAINMENT tests skip without symlink
  privilege — turn on Developer Mode. Plus ripgrep for one more. Quote the
  skip count next to the pass count, always; a skipped test is invisible, not
  green.
- **Three Windows tests are flaky in CI** (two speech-chain races and a
  screen capture) — same commit passed and failed minutes apart; issue #36
  keeps the tally. Do NOT dismiss the screen one as "CI cannot photograph a
  desktop": that would fail every time, and it does not. They are the
  concrete blocker on removing continue-on-error.
- **Four `tests/test_specs_api.py` tests fail on a box where other Claude
  Code projects have specs** — they fail identically on `main`. The specs
  list reads the machine's real `~/.claude`, and the suite's rails do not
  isolate it; a real project (`eligibility` on this box) appears in the
  list. CI's clean runner does not see it. Not fixed as of this writing.
- **Electron:** `npm install` in `electron/` does not unpack the binary;
  `node node_modules/electron/install.js` does.
- The repo now HAS a `.gitattributes` pinning `* text=auto eol=lf`, so the
  CRLF hazard the handoff warns about is closed. Read that file's comment
  before touching it; the template hashes depend on it.

## What NOT to do

- Do not relax `windows/secrets.py`'s DACL check to accept SYSTEM and
  Administrators. It was considered and rejected; the handoff says why.
- Do not "fix" `tests/conftest.py`'s notification rail by narrowing it back
  to one platform. It was inert off macOS for a while and real toasts
  appeared throughout a suite run.
- Do not move the brain's launch prompt back into argv, and do not "simplify"
  it by dropping the per-generation filename — a rotation holds the
  predecessor alive while the successor spawns.
- Do not put a directory back into a cmd.exe command line. It travels as the
  spawn's `cwd` now, on both launcher branches, and that is what makes the
  quoting question go away rather than get answered.
- Do not remove `continue-on-error` from the Windows CI job as a tidy-up —
  see above: it was deferred on purpose until after phase 4, and removing it
  now is blocked on issue #36.
- Do not remove `backgroundThrottling: false` from the Electron window. It
  is why a JARVIS closed to the tray still hears everything, and nothing
  fails loudly without it — a third of what is said simply goes missing.
- Do not drop `--no-ssl` from the supervisor's spawn, or teach `health.js`
  that any failed fetch means "nothing is there". Each of those alone makes
  the app start a second server over a running JARVIS, or fail every launch
  on a dev box.
- Do not widen `electron/policy.js`'s grant. The window holds the
  microphone; it grants the JARVIS origin's microphone and nothing else.
