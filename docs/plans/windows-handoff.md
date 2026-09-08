# Windows handoff

A live working document, not a farewell note: the session spans both
machines and switches between them. Update the state section as things
change.

Read [`cross-platform-port.md`](cross-platform-port.md) for why the phases
are ordered the way they are. This document is only about doing phase 3.

## State right now

- Phase 1 (portability defects) — merged, PR #3.
- Phase 2 (the platform layer) — merged, PR #4.
- Phase 3 — merged, PR #5. The tool token, the launcher and notifications
  were written from documentation.
- **The Windows box is live as of 2026-09-08** and the suite runs on it.
  `fix/windows-portability-defects` carries the first round of corrections.
- macOS suite: 2523 passed, 2 failed. Both failures are
  `tests/test_projects_api.py` (`RuntimeError: Event loop is closed`),
  pre-existing and unrelated, parked until after this phase. **Not re-run
  since the corrections below — the macOS CI leg is the gate for them.**

### The Windows number, and how it moved

| | failed | passed | errors |
|---|---|---|---|
| first run on a real box | 267 | 1788 | 443 |
| after the four fixes below | **266** | **2215** | **11** |

Read that carefully: the ERRORS collapsed and 427 more tests pass, but the
FAILURE count barely moved. The errors were four portability defects in
shared code. The 266 failures are a different thing — they are the port
itself being unfinished, and they are the real work remaining.

Boot is no longer the blocker: `ensure_tool_token()` returns a token, and
`import usage_scan` (and therefore `import server`) succeeds.

### The four defects, none of them in `jarvis_platform/windows/`

All four were in code shared by both platforms, which is why the macOS
suite could never have caught them:

1. **`usage_scan.py:161`** — `datetime(2, 1, 1).timestamp()`. On Windows a
   naive `.timestamp()` raises `OSError(22)` for anything at or before
   1970-01-01 (measured; 9997 fails too, so BOTH bounds raised). This is
   module level, and `server.py:85` imports the module — so the server
   could not start at all. Now computed by subtraction from the epoch.
2. **`data_paths.py:171`** — `os.fdopen(fd, "w")` with no encoding, writing
   a persona full of em-dashes through cp1252. The `UnicodeEncodeError` is
   a **ValueError**, so the `except OSError` two lines down did not catch
   it; it escaped `_sync_template` and killed every fixture that seeds a
   brain home. This one line was 432 of the 443 errors.
3. **~30 `read_text` / `write_text` / `open` calls** with no `encoding=`,
   defaulting to cp1252. `repo_read.py` had the nastier variant —
   `errors="replace"` *without* `encoding=`, which silently mojibakes a
   repository the brain is reading rather than raising.
4. **`os.geteuid()`** evaluated at import inside a `skipif`, taking a whole
   test module down at collection. The two tests it guarded also lose their
   premise here: `os.chmod(p, 0o000)` on Windows returns mode `0o444` and
   the file stays readable (measured), so there is no unreadable file to
   test with. Skipped on Windows rather than adapted.

### Known live problem, not yet fixed

**The suite opens real console windows on Windows.** `tests/test_start_build.py:715`
has a fixture whose docstring reads "No test may open a real Terminal
window" — and it patches `jarvis_platform.macos.launcher` by name. On
Windows `current()` is `WINDOWS`, so the patch lands on a module nothing
calls and `windows/launcher.py` really spawns `wt`/`cmd.exe`. Observed: a
console window appeared running `npm` in a pytest tmp dir. The fix is to
patch `jp.current().launcher` instead of the macOS module, but it is a
fixture macOS depends on too, so it wants the macOS gate run on it.
Suspect the same pattern anywhere a test names a `jarvis_platform.macos.*`
module directly.

## The one thing to understand before touching anything

**Everything in `jarvis_platform/windows/` was written from documentation on
a Mac, not measured on a machine.** That is the opposite of how the rest of
this repository was built, and it is the reason for the checklist below.
Each module says so at the top. Treat every command string in there as a
claim to be tested, not as working code.

The guesses are isolated so a real box corrects each in one place:

| Guess | Lives in | Pinned by | Status |
|---|---|---|---|
| what `icacls <path>` prints | `windows/secrets.py::_parse_aces` | `_ICACLS_OURS`, `_ICACLS_INHERITED` | **confirmed** 2026-09-08, one correction |
| what `whoami /user /fo csv /nh` prints | `windows/secrets.py::_parse_whoami` | `_WHOAMI_SAMPLE` | **confirmed** 2026-09-08, exact |
| the toast AUMID | `windows/notifications.py::_AUMID` | nothing — it fails silently, see below | **still open** — `notify()` returns True, no eyeball yet |
| `wt` / `cmd.exe` argv | `windows/launcher.py::_terminal_argv` | `tests/test_windows_platform.py` | not yet run |

All the samples are in `tests/test_windows_platform.py`. Replace one with
real output and the failures will name everything downstream of it.

The one correction: real inherited ACEs print an `(I)` flag before the
rights — `NT AUTHORITY\SYSTEM:(I)(F)`, not `:(F)`. `_parse_aces` was
unaffected (measured against the real text, it returned the same three
names), but the sample now carries the flag, because a sample that cannot
occur has stopped testing what it names. `_granted_only_to_us` returned
True on the live token file, and `icacls` on it showed exactly one ACE.

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

Two corrections from doing this on a real box (2026-09-08):

* **`py -3.12` may not resolve.** If Python is also installed from the
  Microsoft Store, `py` is the Store launcher and answers 3.13; and a
  winget install puts the real one at
  `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Build the venv
  from that absolute path and the ambiguity disappears. Worth doing
  regardless of `py`: a Store Python runs under package identity, and the
  ACLs it writes are not necessarily the ACLs the icacls check below is
  reading about.
* **`openssl` is likely already on PATH.** Git for Windows ships it at
  BOTH `Git\usr\bin\openssl.exe` and `Git\mingw64\bin\openssl.exe`, and
  the latter is on the default PATH, so plain `openssl` works and the long
  path below is only needed if it does not.

`core.autocrlf` is `true` by default in Git for Windows. Nothing in the
repo pins line endings (there is no `.gitattributes`), so a fresh clone
here checks out CRLF while the repository holds LF. That has not bitten
yet — the edits in this branch were made with LF preserved and the diffs
are clean — but it is worth knowing before blaming a whitespace diff on
something else.

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

1. ~~**`whoami /user /fo csv /nh`**~~ — **DONE 2026-09-08.** Exactly the
   sample's shape: `"proart\kenha","S-1-5-21-…-1001"`. `_parse_whoami`
   returned the pair unchanged. A domain account is still the untested case.
2. ~~**`icacls <data>\jarvis\tool-token`**~~ — **DONE 2026-09-08.** One ACE,
   `PROART\kenha:(F)`, as designed; `_granted_only_to_us` returned True. An
   ordinary file gave the three inherited ACEs, but each carrying `(I)`, and
   `_ICACLS_INHERITED` has been corrected to match. `_parse_aces` read both
   real outputs correctly with no change.
3. **Adoption refuses a foreign file.** Put a file with inherited ACLs at the
   token path and confirm the server refuses to boot rather than adopting
   it. This is the property that stops JARVIS trusting a token somebody else
   chose and knows. **Still open** — the two above were read-only, this one
   writes to the token path and was left for a deliberate run.
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

- ~~**Roster shape.**~~ **ANSWERED 2026-09-08. Same shape**, every key
  `_parse_entry` reads present and spelled identically:
  ```json
  {"pid":33448,"sessionId":"de61a2…","cwd":"C:\\Users\\kenha\\repos\\jarvis",
   "version":"2.1.260","kind":"interactive","entrypoint":"claude-desktop",
   "pidDomain":"win32:proart",
   "messagingSocketPath":"\\\\.\\pipe\\LOCAL\\cc-msg-9f81935021e5e05c7c258918655587c8"}
  ```
  `socket_path` **is a named pipe**, as suspected. `pidDomain` is new and
  is not read by anything yet.

  **This breaks `RosterEntry.steerable` (`session_watch.py:183`), and not
  in the way you would expect.** `Path(sp).exists()` opens a pipe instance
  to stat it, so on a busy pipe it RAISES rather than returning a bool —
  measured, five calls in a row: the first answered True (an instance was
  free), the next four raised `OSError(22) "All pipe instances are busy"`.
  `steerable` is a property, and one of its callers is the sort key at
  `session_watch.py:753`, so the raise does not merely disable steering,
  it takes down roster listing. `os.path.exists()` is NOT the fix: it
  swallows the error and answers False, reporting every Windows session as
  un-steerable. What works, without consuming an instance, is enumerating
  the namespace — `os.listdir("//./pipe")` returned 188 pipes including
  ours. Note the spelling: `\\.\pipe` and `\\.\pipe\` both raise `ENOENT`.
- ~~**Config roots.**~~ **ANSWERED 2026-09-08.** `~/.claude`, so
  `session_watch.DEFAULT_ROOTS` needs no change. It holds `sessions/`,
  `projects/` and `settings.json`. `%APPDATA%\claude` and
  `%LOCALAPPDATA%\claude` both also exist but belong to the desktop app,
  not to the CLI, and hold no roster.
- **`claude -p --output-format stream-json`.** Same line buffering, exit
  codes and `--dangerously-skip-permissions` behaviour? The run pipeline's
  terminal-state invariant depends on the failure modes being ones it
  already handles. **Partly answered:** the `.cmd` question is conditional
  on install method, not universal. The native installer puts a real
  `claude.exe` at `%USERPROFILE%\.local\bin`, which
  `create_subprocess_exec` can run directly; only the npm global is a
  `.cmd` needing a wrapper. Worth deciding which one JARVIS should require
  rather than writing a wrapper for a case the native install avoids.
  (Watch for the two shadowing each other on PATH — the native one wins,
  so an `npm install -g` "upgrade" can leave the older binary in charge.)
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
