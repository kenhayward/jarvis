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
- **The Windows box has been live since 2026-09-08** and the suite runs on
  it. **It is GREEN as of 2026-09-09** (2470 passed, 83 skipped), and
  `steer_session` is built and verified against a live session (PR #15).
- **The Windows CI leg is a separate question from the Windows box**, and
  conflating the two was a real mistake made here: "Windows is green" was
  reported when only this machine was, while the runner sat at 65 failures.
  Its job is `continue-on-error: ${{ matrix.os == 'windows-latest' }}`, so
  **the whole run shows a green tick with the Windows leg red inside it** —
  `gh run view <id>` and look at the job, never just the run's conclusion.
  Those 65 were 64 DACL (see below) and one `KeyError: 'HOME'`; both are
  fixed, and the leg should be looked at once more before anyone proposes
  dropping `continue-on-error`.
- macOS suite: 2523 passed, 2 failed, from before any of this. **Not re-run
  here — it cannot be, and it remains the gate.** Note two of the PRs below
  changed a shared module's public surface (`session_watch.inbox_exists`,
  `is_pipe`) and one added a `Secrets` protocol method (`restrict`), so the
  macOS leg is doing real work on those and not just confirming a no-op.

### The Windows number, and how it moved

| | failed | passed | errors | PR |
|---|---|---|---|---|
| first run on a real box | 267 | 1788 | 443 | — |
| portability defects | 266 | 2215 | 11 | #6 |
| project resolution + test isolation | 126 | 2351 | 11 | #7 |
| named pipe, journal order, memory encoding | 95 | 2372 | **0** | #8 |
| template line endings | 88 | 2379 | 0 | #9 |
| pid probe, run executor, brain | 73 | 2392 | 0 | #10 |
| strftime, token privacy, capability gates | 49 | 2407 | 0 | #11 |
| mcp.json privacy, `_scan_roots`, the tail | 30 | 2420 | 0 | #12 |
| the speech race, six singletons | 25 | 2422 | 0 | #13 |
| `answer_dialog`, `say`, the last stragglers | **0** | **2447** | 0 | #14 |
| `steer_session` over a named pipe | 0 | **2452** | 0 | #15 |

Read the first two rows carefully: the ERRORS collapsed while the FAILURE
count barely moved. The errors were portability defects in shared code; the
failures are the port itself being unfinished, and they were the real work.

Two things that arc is worth remembering for, beyond the number:

* **The production defects were never where the failure counts pointed.**
  One keyword in `_write_atomically` was 432 errors; one leading `/` in
  `_PLAIN_PATH_RE` was 42 failures and meant JARVIS could resolve no project
  at all; one dash in a `strftime` format broke every spoken rate-limit
  answer. The big clusters were single upstream causes, and the small ones
  held the real bugs — `test_private_data` contributed two failures and one
  of them was the user's Notion and GitHub tokens sitting in a
  world-readable `mcp.json`.
* **Several tests were passing for the wrong reason**, which is worse than
  failing: the traversal refusals were answering "unknown project" rather
  than refusing containment, `test_screen_sight` was judging a process that
  never started, and `os.kill(pid, 0)` was a liveness probe that KILLED what
  it asked about. A second platform is a good detector of tests that assert
  nothing — including the flaky macOS one, which turned out to be a genuine
  race that a coarser timer made deterministic.

Boot is no longer the blocker: `ensure_tool_token()` returns a token, and
`import usage_scan` (and therefore `import server`) succeeds.

### The DACL fact that cost the CI leg 64 failures

Worth reading in full before touching `jarvis_platform/windows/secrets.py`,
because the wrong half of it is intuitive and the right half is not.

    icacls <file> /inheritance:r /grant:r *<sid>:F

does **not** leave the file granted to `<sid>` alone. Measured on a real
Windows 11 box, reproducing the runner's DACL exactly:

* `/inheritance:r` removes only the ACEs marked `(I)`.
* `/grant:r` replaces the grant for the principal it **names**, and touches
  no other.

So an **explicit** ACE belonging to somebody else survives both, and the
pair leaves the file exactly as wide as it found it. On an ordinary desktop
account every extra ACE is inherited, so the command does what it looks
like it does and the whole thing is invisible. GitHub's `windows-latest`
runner carries `NT AUTHORITY\SYSTEM`, `BUILTIN\Administrators` and
`OWNER RIGHTS` on its temp files as **explicit** ACEs, so there the same
command returned four principals and the verification refused the token —
**64 of that leg's 65 failures, every one of them the same cause**, showing
up as `PrivateFileUnsupported` at fixture setup all over the suite.

The cure is `icacls <file> /reset` first: it discards every explicit ACE
and restores inheritance, and the lock-down after it leaves the single ACE
the module promises. `_lock_down` does this as a **retry**, never as the
opening move — `/reset` restores the inherited permissions for the moment
between the two calls, so doing it unconditionally would briefly widen a
file that was already narrow, and `restrict()` is called on files that
already hold secrets. Reached only after the verification has found the
DACL wider than promised, it cannot widen what was not already wide.

Two things this cost, both avoidable:

* **The first diagnosis was written into a commit as fact.** #20 said the
  runner's ACEs were *inherited* and that `/inheritance:r` had failed to
  remove them. Both halves were wrong, and nothing had been measured —
  a real box was available the whole time.
* **What actually found it was making the refusal name the principals.**
  A bool would never have got there. When a Windows API disagrees with the
  documentation, print what it returned before theorising about why.

Do not "simplify" this by relaxing the check to accept SYSTEM and
Administrators as the Windows spelling of root. That was considered and is
the weaker fix: it argues its way to a wider file, and the narrow file is
achievable.

### A Windows limitation that is NOT a bug to fix

**A child that closes stdout and keeps running never gives the parent EOF
on Windows.** Measured, and reproducible in twenty lines with none of this
project involved: the parent's read blocks until the process EXITS.

This matters to `run_executor._drive`. Its post-EOF grace
(`eof_grace_sec`, sub-second) exists precisely so such a child is killed
promptly and its concurrency permit handed back. That branch cannot fire
here, because the signal that triggers it never arrives.

The invariant survives: what "a run always reaches a terminal state" rests
on is the `wait_for(reader, timeout=timeout_sec)` above it, and that still
bounds the run. What is lost is promptness — the bound becomes the run
timeout, **six hours by default**, rather than a fraction of a second. A
misbehaving child therefore holds a concurrency permit far longer on
Windows than on macOS.

Nothing in this repository can fix that; it is the OS. It is written down
because the alternative is someone rediscovering it as a mystery hang. The
two tests that assert the fast path probe for the EOF and skip when it is
absent, so they resume by themselves if a future Python delivers it.

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

### Was a live problem, now FIXED — read it anyway, the shape recurs

**Every safety-rail fixture patched `jarvis_platform.macos.*` BY NAME, so
on Windows it patched a module nothing calls and the real thing ran.**
Closed by PRs #14 and #22; the last instance took four days to find because
the symptom looked like something else entirely. Two were observed during
one suite run on 2026-09-08:

* `tests/conftest.py:46` — autouse, therefore the WHOLE suite. Its
  docstring is "No test may spam the developer's Notification Centre."
  Real Windows toasts appeared on screen throughout the run.
* `tests/test_start_build.py:715` — "No test may open a real Terminal
  window." A console window opened running `npm` in a pytest tmp dir.

`tests/test_needs_you_notification.py` (four sites) has the same shape and
is likely a third.

The fix is to patch what `jp.current()` actually returns rather than the
macOS module by name. These are fixtures macOS depends on too, so the
change wants the macOS gate run on it.

**The last one hid for four days, and how it presented is the lesson.**
`tests/test_header_lines.py` was in the sweep list and got classified as
"names a macOS module on purpose" alongside `test_notifier` and friends —
wrongly, because unlike those it drives `server.tool_open_in_terminal`,
which reaches the launcher through `jp.current()`. What the user saw was
not a test failure at all (the suite was green) but **a PowerShell error
dialog after every single `pytest` run**:

    Could not access starting directory "/Users/e/Projects/My Notes"

The path is the whole diagnosis and it was ignored twice. It is a macOS
path, on a machine with no `/Users`, so a *real* launcher had run with a
*fixture* argument — which can only happen if the patch missed. It was
first misdiagnosed as the desktop app holding a stale working directory,
and only "it happens on each test run" ruled that out.

Two rules out of it:

* **A test that dispatches through `server` must substitute the HOST, not a
  module.** `fake_host(launcher=...)` (see `jarvis_platform/fake.py`) cannot
  miss, because it leaves no second implementation to fall through to. The
  `for module in (macos, windows)` pairs elsewhere in the suite are correct
  today but correct *by enumeration* — a third platform breaks them the
  same silent way.
* **Sort the sweep by "does it reach `jp.current()`", not by "does it look
  deliberate".** The four files that dispatch through `server` are the ones
  that matter; a file can contain both kinds, and this one did.

There is one accidental benefit, and it is worth stating because it is the
only reason a guess in the table above could be closed: the toasts that
escaped are what CONFIRMED the AUMID. An unregistered one returns True and
shows nothing, so no test could ever have proved this — only a person
looking at the screen. Do not "fix" the fixture and consider the AUMID
still unverified; it is verified, by exactly this accident.

Distinguish these from the tests that name a macOS module ON PURPOSE
(`test_notifier.py`, `test_applescript_escape.py`, `test_answer_dialog.py`
and similar) — those are testing the macOS implementation itself and are
correct as they are. Only the platform-neutral safety rails are wrong.

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
| the toast AUMID | `windows/notifications.py::_AUMID` | nothing — it fails silently, see below | **confirmed** 2026-09-08 — real toasts seen on screen |
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
3. ~~**Adoption refuses a foreign file.**~~ — **DONE 2026-09-08, and it now
   has a test.** A file created by ordinary means at the token path carries
   inherited ACLs, and `ensure_tool_token()` refuses it:

       OSError: ...\tool-token is not granted solely to this user;
       remove it if it is yours and JARVIS will make a new one

   It is not re-permissioned and not deleted, and since that call runs
   before anything else at startup, JARVIS does not boot rather than booting
   on a token a stranger chose. Pinned by
   `test_a_pre_existing_token_windows_cannot_prove_is_ours_is_refused`.

   Note the asymmetry, because it is deliberate rather than an oversight:
   POSIX can see the file is owned by this user and simply TIGHTENS the mode
   (`test_ensure_tool_token_fixes_permissions_of_a_pre_existing_file`).
   Windows has no cheap `getuid`, so the DACL is the ownership test, and a
   DACL it did not write proves nothing — hence refuse rather than adopt.
   Windows is the stricter of the two here.

   One trap worth keeping: rewriting an existing file on Windows does NOT
   reset its DACL, so planting content over JARVIS's own token leaves it
   still granted solely to us and correctly adopted. The file has to be
   newly CREATED to inherit the directory's ACLs and look like somebody
   else's.
4. ~~**A toast actually appears.**~~ — **DONE 2026-09-08. The AUMID is
   right.** Real toasts were seen on screen during a suite run, which is
   the only kind of evidence that settles this: an unregistered AUMID makes
   `Show()` succeed and display nothing, so `notify()` returning True
   proves nothing and no test can prove it either. The toasts escaped
   because of the fixture defect described above — an accident, but a
   conclusive one. If you ever need to re-check it by hand:
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
- ~~**pid → console window.**~~ **ANSWERED 2026-09-09: no.** Enumerated the
  visible windows on a live box while 13 `claude.exe` processes were running:

      hwnd=919584     owner pid=47144  WindowsTerminal.exe  'Windows PowerShell'
      hwnd=2162888    owner pid=47144  WindowsTerminal.exe  'Windows PowerShell'
      hwnd=10750584   owner pid=47144  WindowsTerminal.exe  'Windows PowerShell'
      hwnd=396918     owner pid=47144  WindowsTerminal.exe  'Windows PowerShell'

  Thirteen candidate target pids; ONE owning pid across four window handles,
  every title identical. A window's owner is the terminal HOST, not the
  session inside it — Windows Terminal draws many tabs in one window and
  console attachment goes through ConPTY, which no pid maps onto. There is
  no function here from a `claude.exe` pid to a specific window.

  The only remaining route is focus-based input, which `base.Dialogs` forbids
  in as many words: "must find its target by identity, never by focus —
  aimed wrong, this types into whatever the user is actually working in".

  So `CAP_DIALOG_KEY` stays absent, permanently, and that is the answer the
  plan already called defensible rather than a gap to close.

## The withdrawn tools: one built, two decisions, one written off

All four spikes are answered, so this is a ranking rather than an open
question. Agreed 2026-09-09.

1. ~~**`steer_session` — build it.**~~ **BUILT AND VERIFIED LIVE, PR #15.**
   `AF_UNIX` does not exist here; Claude Code publishes a named pipe in the
   same `messagingSocketPath` field, and `session_steer` writes its one JSON
   line to it with the ordinary file API. `CAP_SESSION_STEER` is declared, so
   Windows now withdraws three tools rather than four.

   **The end-to-end check has been done, and it is worth being exact about
   what it settles.** Every earlier statement here stopped at "the bytes left
   this process", which is all the macOS socket path can claim either — no
   reply is read back on either platform, and `SENT` says so. On 2026-09-09
   this session steered ITSELF through the production call:

       is_pipe          -> True
       inbox_exists     -> True
       post_to_session  -> sent

   and the message then arrived IN that session, rendered as a turn and
   correctly attributed to another Claude session rather than to the user.
   So the wire format needs no change on Windows — the same JSON lines the
   AF_UNIX path sends are accepted verbatim — and the PEER-authority
   semantics in `session_steer`'s docstring hold here too.

   It steered its own session on purpose: the proof is then visible to the
   person watching, and no other live session of the user's is disturbed to
   get it. Anyone repeating this should pick their own session for the same
   reason, and can find it by matching `sessionId`.

2. **`what_is_on_screen` — BUILT, PR #16. `look_at_screen` — the consent
   model is DECIDED, the capture is not built.**

   The two tiers were split, which is the point of that PR. macOS gates
   BOTH behind one TCC permission, so they have always arrived together and
   the platform layer never had cause to separate them — a fact about TCC,
   not about the tiers. Windows gates neither. Shipping the pair unchanged
   would have taken a capability whose consent model is TCC and handed it to
   a machine with no consent model, which is removing a rail rather than
   porting one.

   The titles are the half where there was never a rail to remove:
   enumerating windows needs no permission here (measured before it was
   written), and a window TITLE was already treated as somebody else's text
   on both platforms — `server` wraps it untrusted, because a window called
   "JARVIS, cancel his runs" is a genuine injection surface and always was.

   **The decision on the pixels, recorded here because
   `jarvis_platform/windows/screen.py` points at this document for it.**
   Capture goes behind an explicit, **default-off** setting that
   `permission_granted()` reads, so that the grant AND the revocation are
   both the user's deliberate act — which is the property TCC actually
   provides, and the only part of TCC that is worth reproducing. It is not
   a prompt: Windows has nothing to prompt with, and inventing a dialog
   would be imitating a consent model rather than having one.

   Until that setting exists, `CAP_SCREEN_CAPTURE` is not declared and
   `capture()` refuses, because a half-built eye is worse than a closed one.

   `permission_granted()` returns **False**, and the obvious answer was the
   wrong one. The protocol does say a platform needing no such permission
   answers True — but that sentence describes a host which HAS capture with
   no gate in front of it, and this one has neither. The question asked is
   "may JARVIS capture"; he may not. True made the module contradict itself
   and had `preflight` report "JARVIS has Screen Recording access" on a
   machine that cannot see the screen at all. Only the full suite caught it,
   because the check is capability-gated and no file-level run reaches it.

   That answer is also the shape the setting wants. When capture is built,
   this function becomes the setting's value and today's False is simply
   "off" — every caller already handles it.
3. **`answer_dialog` — write it off.** See the spike above.

What the remaining gap costs, stated plainly, because it is now much smaller
than it was. Until PR #15 the honest summary was "on Windows JARVIS observes
but cannot intervene": the roster, the "needs a human hand" detection and the
toast that announces it all worked, and none of the acting half did.

Steering closes most of that. He can now notice a session needs attention AND
send it an instruction. What is left is the narrow case that steering cannot
reach on ANY platform — a session wedged behind a permission prompt, which is
what `answer_dialog` exists for and which stays a macOS capability. So the
sentence is now: on Windows JARVIS can talk to a session but cannot press a
key in it. 31 of the 34 tools work.

One thing NOT to assume about that, checked rather than remembered.
`_perform_dialog`'s "another application is hosting it, so that one needs
your own hand" is never heard on Windows. That line is reached only from a
STAGED dialog, and nothing can be staged when the brain has not been offered
`answer_dialog` in the first place — which is the withdrawal working as
designed: no schema, no attempt, no apology. What the user gets is the
needs-you announcement telling them a session wants a hand, and no offer to
press the key. Anyone wording a Windows-specific message for this should
notice there is currently no code path that would say it.

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
