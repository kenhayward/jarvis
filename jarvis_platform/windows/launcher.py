"""Windows launching: a terminal, a browser, an editor.

Written from documentation and **since corrected by measurement** — see
`windows/secrets.py` for what that means. The argv this module builds is
pinned by `tests/test_windows_platform.py` (not `test_windows_launcher.py`,
which has never existed), which runs on any platform because it mocks the one
subprocess seam.

What a real box had to confirm is that those argv actually do what they say,
and on 2026-09-09 it did: `terminal`'s `wt` branch was right, and its cmd.exe
fallback was broken in two ways at once — a test can pin the string a
function returns and still tell you nothing about whether it works. See
`_terminal_argv`.

The interface's whole point is here: `terminal` takes `cwd` and `command`
apart, so each can travel by the route that needs no quoting at all — the
directory as an argv entry or as the spawn's own `cwd`, the command through
a caller that permits no metacharacter. `shlex.quote` is never used here; it
is POSIX and this is cmd.exe, so it would be actively wrong. The lesson of
the fallback below is that the moment either one becomes TEXT in a command
line, the quoting rules stop being Python's and start being cmd.exe's.

Reached as `jarvis_platform.current().launcher`. Each call returns
{"success": bool, "confirmation": str}; `editor` also returns "editor".
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess

log = logging.getLogger("jarvis.platform.launcher")

LAUNCH_TIMEOUT = 15.0

# `subprocess.CREATE_NEW_CONSOLE` exists only on Windows, and this module is
# imported on every platform — `tests/test_windows_platform.py` runs the whole
# argv suite on the macOS gate by mocking the one subprocess seam. Read through
# `getattr` so the import cannot take that suite down off Windows; the flag is
# only ever passed on the branch that runs here.
_CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

# Windows Terminal if it is there, and the console host if it is not. `wt`
# is the modern default (shipped in Windows 11, installable on 10) and is
# the only one of the two that can be told a starting directory without a
# shell line, which is why it is preferred: `wt -d <dir>` needs no quoting
# of `dir` at all, because it is its own argv entry.
_WT = "wt.exe"
_CMD = "cmd.exe"


async def _spawn(argv: list[str], cwd: str | None = None,
                 new_console: bool = False) -> tuple[bool, str]:
    """Start something and let it go. Never raises.

    These are launches, not jobs: `wt` and `explorer` return immediately
    having handed off to a window that outlives us, so the wait is only
    long enough to catch a spawn that failed outright.

    `cwd` is how a directory reaches a program that has no flag for one. It
    is passed to the OS as data and never composed into a command line —
    which is the whole reason this module exists, and which the cmd.exe
    fallback below used to get wrong.

    `new_console` is for the one caller that must give the USER a window
    rather than hand JARVIS a child. It changes two things together, and
    they cannot be separated:

    * no pipes. Piped stdio would leave the user looking at an empty console
      while the shell talked to us — measured, `cmd /k`'s prompt arrived on
      the parent's pipe and nothing was on screen.
    * no wait. With no pipes there is nothing to read, and `cmd /k` never
      exits by design, so `communicate()` would block for the whole
      LAUNCH_TIMEOUT on every single terminal the user opens.

    What is given up is the stderr text on failure. A launch that fails for
    the reason that actually happens — the program is not there — still
    raises OSError below and is still reported.
    """
    if new_console:
        # `creationflags` is Windows-only and raises ValueError on POSIX —
        # which is NOT an OSError and would escape the handler below. That is
        # reachable off Windows despite the module's name: `new_console` is
        # decided by "no wt.exe on PATH", and there is no wt.exe on a Mac,
        # where this file's whole test suite runs. Omitted rather than passed
        # as 0 so the argument never reaches a platform that rejects it.
        flags = {"creationflags": _CREATE_NEW_CONSOLE} if _CREATE_NEW_CONSOLE else {}
        try:
            await asyncio.create_subprocess_exec(*argv, cwd=cwd, **flags)
        except OSError as e:
            return False, f"could not launch {argv[0]}: {e}"
        return True, ""

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        return False, f"could not launch {argv[0]}: {e}"
    try:
        _out, err = await asyncio.wait_for(proc.communicate(),
                                           timeout=LAUNCH_TIMEOUT)
    except asyncio.TimeoutError:
        # It is still running, which for a window launcher means it worked.
        return True, ""
    if proc.returncode not in (0, None):
        return False, err.decode("utf-8", "replace").strip()[:200]
    return True, ""


def _windows_terminal() -> str | None:
    """`wt.exe`'s path, or None. One lookup so `_terminal_argv` and
    `terminal` cannot disagree about which branch is being taken — they
    make different decisions off the same fact."""
    return shutil.which(_WT)


def _terminal_argv(cwd: str, command: str) -> list[str]:
    """The argv that opens a terminal, optionally running `command`.

    Isolated and pinned by tests because it is the quoting decision this
    whole interface exists for.

    **The directory is not here on either branch, and that is the point.**
    With `wt` it is its own argv entry (`-d <dir>`) and needs no quoting
    whatever it contains. With cmd.exe it is not in the command line at all
    — it travels as the spawn's `cwd`. Only `command` reaches a shell, and
    it reaches cmd.exe's, not a POSIX one; its callers have already been
    through `builds.command_problem`, which permits no shell metacharacter
    at all, so there is nothing here to escape.

    The fallback used to compose `cd /d "<dir>" && <command>` into one argv
    element, and it had never been run. Measured on a real box 2026-09-09:
    Python's `list2cmdline` escapes an embedded `"` as `\\"`, which is
    CommandLineToArgvW's convention and NOT cmd.exe's — cmd.exe has no
    escape character inside quotes, as the paragraph above has always said.
    cmd answered "The filename, directory name, or volume label syntax is
    incorrect.", `cd /d` failed, `&&` short-circuited so the command never
    ran, and `_spawn` reported success throughout. The old test pinned the
    STRING this function returned and so never noticed; the tests now pin
    the rule — no argv element may carry a quote.

    That also retires the `cd /d` question rather than answering it: with no
    `cd` there is no drive to change, because the OS sets the directory
    before the shell starts.
    """
    wt = _windows_terminal()
    if wt:
        argv = [wt]
        if cwd:
            argv += ["-d", cwd]
        if command:
            argv += ["cmd.exe", "/k", command]
        return argv

    cmd = shutil.which(_CMD) or _CMD
    return [cmd, "/k", command] if command else [cmd]


async def terminal(*, cwd: str = "", command: str = "") -> dict:
    """Open a terminal window at `cwd`, optionally running `command`."""
    # Each branch gets exactly the mechanism it needs and nothing more.
    #
    # `wt` already carries the directory as `-d`, so it is not given `cwd` as
    # well: the only difference that would make is to a directory that does
    # not exist, where the spawn would start failing on the one branch that
    # has always worked. It draws its own window too, so a console handed to
    # it would be a stray empty one.
    wt = _windows_terminal()
    ok, err = await _spawn(_terminal_argv(cwd, command),
                           cwd=None if wt else (cwd or None),
                           new_console=not wt)
    if not ok:
        log.error("terminal failed: %s", err)
    return {
        "success": ok,
        "confirmation": "Terminal is open, sir." if ok
        else "I had trouble opening a terminal, sir.",
    }


async def browser(url: str, which: str = "chrome") -> dict:
    """Open `url` in the user's browser.

    `os.startfile` rather than a named application, and rather than the
    `webbrowser` module: it hands the URL to the shell's own association,
    which is the user's default browser and the thing they expect. `which`
    is accepted for interface compatibility and honoured only when that
    browser is actually on PATH — naming Chrome and silently getting Edge
    would be worse than saying which one opened.

    The URL is passed as data to a shell association, never composed into a
    command line, which is the same property `notifications` keeps for its
    argv. There is no AppleScript-shaped injection surface here.
    """
    app_name = "your browser"
    exe = None
    if which and which.lower() != "default":
        exe = shutil.which(f"{which.lower()}.exe") or shutil.which(which.lower())
        if exe:
            app_name = which.capitalize()

    if exe:
        ok, err = await _spawn([exe, url])
        if not ok:
            log.error("browser (%s) failed: %s", app_name, err)
        return {"success": ok,
                "confirmation": f"Pulled that up in {app_name}, sir." if ok
                else f"{app_name} ran into a problem, sir."}

    try:
        os.startfile(url)                          # noqa: S606 - Windows only
    except (OSError, AttributeError, ValueError) as e:
        log.error("browser failed: %s", e)
        return {"success": False,
                "confirmation": "Your browser wouldn't open that, sir."}
    return {"success": True, "confirmation": "Pulled that up, sir."}


async def editor(path: str) -> dict:
    """Open a file or directory in VS Code, else in the system default.

    `code.cmd` is what the Windows installer puts on PATH — confirmed on a
    real box, along with the fact that `shutil.which("code")` finds it too
    through PATHEXT. The full name is asked for first so the answer does not
    depend on that.

    This used to say a `.cmd` "cannot be executed by
    `create_subprocess_exec`". That is wrong, measured 2026-09-09: it runs
    fine, because Windows reaches a batch file through the command
    processor. What the command processor then does is re-parse the
    ARGUMENTS — `%NAME%` in `path` would be expanded here — which is the
    real cost and is why `preflight`'s `claude_shim` check exists.
    """
    binary = shutil.which("code.cmd") or shutil.which("code")
    if binary:
        ok, err = await _spawn([binary, str(path)])
        if not ok:
            log.error("editor failed: %s", err)
        return {"success": ok, "editor": "VS Code",
                "confirmation": "Opened that in VS Code, sir." if ok
                else "VS Code wouldn't open that, sir."}

    try:
        os.startfile(str(path))                    # noqa: S606 - Windows only
    except (OSError, AttributeError, ValueError) as e:
        log.error("editor failed: %s", e)
        return {"success": False, "editor": "your editor",
                "confirmation": "I couldn't open an editor, sir."}
    return {"success": True, "editor": "your editor",
            "confirmation": "Opened that in your editor, sir."}
