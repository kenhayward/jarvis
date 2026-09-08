# Windows handoff

A live working document, not a farewell note: the session spans both
machines and switches between them. Update the state section as things
change.

Read [`cross-platform-port.md`](cross-platform-port.md) for why the phases
are ordered the way they are. This document is only about doing phase 3.

## State right now

- Phase 1 (portability defects) — merged, PR #3.
- Phase 2 (the platform layer) — merged, PR #4.
- Phase 3 — `feat/windows-platform`. The tool token, the launcher and
  notifications are written; nothing is verified.
- macOS suite: 2523 passed, 2 failed. Both failures are
  `tests/test_projects_api.py` (`RuntimeError: Event loop is closed`),
  pre-existing and unrelated, parked until after this phase.

## The one thing to understand before touching anything

**Everything in `jarvis_platform/windows/` was written from documentation on
a Mac, not measured on a machine.** That is the opposite of how the rest of
this repository was built, and it is the reason for the checklist below.
Each module says so at the top. Treat every command string in there as a
claim to be tested, not as working code.

The guesses are isolated so a real box corrects each in one place:

| Guess | Lives in | Pinned by |
|---|---|---|
| what `icacls <path>` prints | `windows/secrets.py::_parse_aces` | `_ICACLS_OURS`, `_ICACLS_INHERITED` |
| what `whoami /user /fo csv /nh` prints | `windows/secrets.py::_parse_whoami` | `_WHOAMI_SAMPLE` |
| the toast AUMID | `windows/notifications.py::_AUMID` | nothing — it fails silently, see below |
| `wt` / `cmd.exe` argv | `windows/launcher.py::_terminal_argv` | `tests/test_windows_platform.py` |

All the samples are in `tests/test_windows_platform.py`. Replace one with
real output and the failures will name everything downstream of it.

## Setting the machine up

```
winget install Python.Python.3.12 OpenJS.NodeJS.LTS Git.Git Microsoft.WindowsTerminal
npm install -g @anthropic-ai/claude-code
claude                      # log in — the brain runs on the subscription
```

```
git clone https://github.com/kenhayward/jarvis
cd jarvis
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
cd frontend && npm ci && cd ..
copy .env.example .env
```

The certs are not optional for the Vite dev workflow — `vite.config.ts`
hard-codes `https://localhost:8340`. There is no `openssl` on a stock
Windows, but Git for Windows ships one:

```
"C:\Program Files\Git\usr\bin\openssl.exe" req -x509 -newkey rsa:2048 ^
  -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

## Start here: does it boot?

`ensure_tool_token()` is called at `server.py:990`, **before** the
`JARVIS_BRAIN_AUTOSTART` check, so it runs unconditionally. Until it works,
nothing else on Windows is reachable. Measured by forcing that branch on
macOS: 47 failures and 291 errors against a baseline of 2, so this one
function is most of what a Windows run currently cannot do.

```
python -c "import data_paths; print(data_paths.ensure_tool_token())"
```

If that prints a token, run the suite and record the number — it is the
figure the Windows CI job has been reporting since phase 1, and it should
have dropped a long way.

```
pytest -q
```

## Verify the guesses, in this order

Each of these takes a minute and either confirms a sample or replaces one.

1. **`whoami /user /fo csv /nh`** — compare with `_WHOAMI_SAMPLE`. A domain
   account is the interesting case; the SID is used for the grant precisely
   because the name is ambiguous.
2. **`icacls <data>\jarvis\tool-token`** after a successful boot — compare
   with `_ICACLS_OURS`. It should be exactly one ACE naming you.
   Then check a file JARVIS did *not* create (`icacls` on any ordinary file)
   against `_ICACLS_INHERITED`.
3. **Adoption refuses a foreign file.** Put a file with inherited ACLs at the
   token path and confirm the server refuses to boot rather than adopting
   it. This is the property that stops JARVIS trusting a token somebody else
   chose and knows.
4. **A toast actually appears.** `_AUMID` is the likely failure and it fails
   *silently* — an unregistered AUMID makes `Show()` succeed and display
   nothing. Drive it directly rather than waiting for a real notification:
   ```
   python -c "import asyncio; from jarvis_platform.windows import notifications as n; print(asyncio.run(n.notify('JARVIS','test','sub')))"
   ```
   `True` with no toast on screen means the AUMID is wrong.
5. **`wt -d "C:\a b\c"`** opens where it says. Then without Windows Terminal
   installed, check the `cmd.exe` fallback changes drive — `cd /d` is there
   because a bare `cd` does not, and getting it wrong opens the wrong
   directory while reporting success.
6. **`code.cmd`** is what is on PATH, not `code`.

## Then: the spikes only this machine can answer

Record the answers in the PR or here; each one decides whether a capability
gets built at all.

- **Roster shape.** What is in `~/.claude/sessions/<pid>.json` on Windows —
  same shape, and what does `socket_path` contain? `session_watch.py` and
  session steering are both built on the answer. If it is a named pipe
  (`\\.\pipe\...`), ordinary file I/O may reach it; `socket.AF_UNIX` is not
  exposed by CPython here.
- **Config roots.** Does the CLI use `~/.claude` on Windows, or `%APPDATA%`?
  `session_watch.DEFAULT_ROOTS` assumes the former.
- **`claude -p --output-format stream-json`.** Same line buffering, exit
  codes and `--dangerously-skip-permissions` behaviour? The run pipeline's
  terminal-state invariant depends on the failure modes being ones it
  already handles. Also: is it `claude.cmd`? `create_subprocess_exec` cannot
  run a `.cmd` directly — phase 1 fixed the *splitting*, not the *spawning*.
- **pid → console window.** Is there any mechanism that maps a Claude Code
  pid to a specific console window with the certainty a tty gives? If not,
  `answer_dialog` stays a macOS capability and `CAP_DIALOG_KEY` is never
  declared here. That is a defensible answer for a tool that sends synthetic
  keystrokes.

## What can still be done on the Mac in parallel

So the two machines do not block each other:

- The Windows preflight check set (`preflight.py` currently has no Windows
  branch; Accessibility and Screen Recording are already skipped by
  capability, but the remedies are macOS-worded).
- The `.cmd` spawn wrapper for `claude.cmd` — the shape is decidable, the
  behaviour is not.
- The macOS-worded spoken lines in `server._perform_dialog` ("macOS won't
  let me send keystrokes"), which should come from the platform.
- Anything in phase 4.

## Rules that do not change on Windows

- **Declare a capability in the same commit as its implementation**, never
  before. `jarvis_platform/windows/__init__.py` is the honest list of what
  works, not a wish list. Everything absent is withdrawn, which means the
  brain is never shown the tool and never apologises for it.
- **The macOS suite is still the gate.** It cannot be run here, so push and
  watch the macOS CI leg. A green Windows run that reddens macOS is a
  regression, not progress.
- **Argv, not command strings**, for anything carrying text from a
  transcript. See `windows/notifications.py` for why the values go in the
  environment rather than into the script.
- PRs to `kenhayward/jarvis`, base passed explicitly:
  `gh pr create --repo kenhayward/jarvis --base main`.
