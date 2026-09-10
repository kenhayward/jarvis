# Pick up here

Paste the block below into a fresh Claude Code session in this repository.
Everything in it is checkable against the repo — if a claim here disagrees
with the code, trust the code and fix this file.

Last updated 2026-09-09, at the end of the Windows session that closed the
last two phase 3 items — `claude.cmd` and the terminal launcher. Both were
"verify a guess" tasks, and both guesses were wrong in the same direction.

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

So the next real work is phase 4: server-side speech recognition. Read
docs/plans/phase-4-speech.md. 4-zero, 4a and 4b are DONE (2026-09-10); 4c is
next.

Read 4d before anything else in that document. The design was overturned by
its own bake-off: recording twenty utterances in a real room showed every
candidate engine transcribes JARVIS rather than the user during barge-in,
12 takes out of 12, and NOT because he was louder — in three of four he was
at or below the user's own level. So echo cancellation went from "first
thing to cut" to required, and the audio boundary went from segments to
continuous streaming. Do not re-argue that from the earlier sections; they
are marked SUPERSEDED and left in place on purpose.

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
  newline", "no argv element contains a quote".
- Run the full suite (bare `pytest`, no flags) before pushing, and the
  frontend gates (cd frontend && npx tsc --noEmit && npm run build) if you
  touch frontend/.
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
- **Two Windows tests are flaky in CI** (a speech-chain race and a screen
  capture) — same commit passed and failed minutes apart. Do NOT dismiss the
  screen one as "CI cannot photograph a desktop": that would fail every time,
  and it does not. They are the concrete blocker on removing
  continue-on-error.
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
- Do not remove `continue-on-error` from the Windows CI job — see above, it
  is deferred on purpose until after phase 4.
