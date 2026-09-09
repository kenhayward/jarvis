# Pick up here

Paste the block below into a fresh Claude Code session in this repository.
Everything in it is checkable against the repo — if a claim here disagrees
with the code, trust the code and fix this file.

Last updated 2026-09-09, at the end of the Windows session that built screen
capture.

---

```
We're finishing the macOS→Windows port of JARVIS. Read
docs/plans/windows-handoff.md first — the "Picking this up on another
machine" and "What is left" sections at the top — then
docs/plans/cross-platform-port.md for why the phases are ordered as they
are. CLAUDE.md is the standing guidance for the repo.

Where things stand: phase 3 is one item from done. Windows runs the same
suite green on a real box and withdraws exactly one tool (answer_dialog,
permanently and by decision). The platform layer (jarvis_platform/) is the
only place that knows what a machine can do.

The one open code item is spawning claude.cmd. asyncio.create_subprocess_exec
cannot run a .cmd or .bat directly; claude_env.split_command fixed the
splitting half in phase 1 and its docstring says the spawning half was left
to the call sites — brain.py and run_executor.py — and never done. It has
not bitten on the Windows box because Claude Code there is claude.exe from
the native installer, but README/CLAUDE.md tell users to npm install, and npm
on Windows writes a claude.cmd shim. Every test fakes claude at the
subprocess seam, so the suite cannot catch it.

Please start by VERIFYING it rather than fixing it: install the npm shim
alongside the native binary, point JARVIS_CLAUDE_PATH at the .cmd, and try a
real run. If it spawns fine, say so and we'll close the item. If it doesn't,
fix both call sites and mind that the argument quoting becomes cmd.exe's
rules rather than CommandLineToArgvW's.

Two smaller things after that, both in "What is left":
- windows/launcher.py::_terminal_argv is the last unverified guess in the
  handoff's table — a successful terminal open has never actually been seen.
- The Windows CI job still carries continue-on-error. Nothing is known to
  fail there now, so it's ready to come off as its own change once a run or
  two is clean. Check the JOB, not the run's conclusion: a green tick can
  hold a red Windows leg inside it.

Some ground rules this port has been run under, which matter more than usual
here:
- jarvis_platform/windows/ was written from documentation and is being
  corrected by measurement. Measure on the real machine before writing a
  comment as fact. I got this wrong once and put a wrong diagnosis into a
  commit message (PR #20 vs #24 — the DACL story in the handoff).
- Declare a capability in the same commit as its implementation, never
  before. A capability says what is BUILT; whether JARVIS may use it today
  is a separate runtime question its module answers.
- A platform that cannot do something withdraws the tool; it never fakes it.
- Tests that dispatch through server must substitute the HOST
  (jarvis_platform.fake.fake_host), never patch jarvis_platform.macos.* by
  name. That mistake has been made three times in this repo and hides until
  the suite runs off macOS.
- Run the full suite (bare `pytest`, no flags) before pushing, and the
  frontend gates (cd frontend && npx tsc --noEmit && npm run build) if you
  touch frontend/.
- PRs go to kenhayward/jarvis: gh pr create --repo kenhayward/jarvis --base main
```

---

## If you are on the Mac

The macOS suite is the gate and cannot be run from the Windows box. Several
merged PRs changed shared surfaces (`session_watch.inbox_exists` / `is_pipe`,
`Secrets.restrict`, `Screen.CAPTURE_GATE`, `tests/conftest.py` rails), so the
first useful thing on a Mac is simply:

```bash
pytest
```

and reporting the number. The last figure recorded here for macOS is 2523
passed / 2 failed, from *before* any of this work — it is stale, and nobody
has re-run it since.

## What NOT to do

- Do not remove `continue-on-error` from the Windows CI job on a prediction.
- Do not relax `windows/secrets.py`'s DACL check to accept SYSTEM and
  Administrators. It was considered and rejected; the handoff says why.
- Do not "fix" `tests/conftest.py`'s notification rail by narrowing it back
  to one platform. It was inert off macOS for a while and real toasts
  appeared throughout a suite run.
