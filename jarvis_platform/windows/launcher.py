"""Windows launching: a terminal, a browser, an editor.

**Written from documentation, not from measurement** — see
`windows/secrets.py` for what that means and how to correct it. The argv
this module builds is pinned by `tests/test_windows_launcher.py`, which
runs on any platform because it mocks the one subprocess seam; what a real
box has to confirm is that those argv actually do what they say.

The interface's whole point is here: `terminal` takes `cwd` and `command`
apart, so this can quote for cmd.exe while the macOS launcher quotes for a
POSIX shell. `shlex.quote` is never used here — it would be actively wrong.

Reached as `jarvis_platform.current().launcher`. Each call returns
{"success": bool, "confirmation": str}; `editor` also returns "editor".
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

log = logging.getLogger("jarvis.platform.launcher")

LAUNCH_TIMEOUT = 15.0

# Windows Terminal if it is there, and the console host if it is not. `wt`
# is the modern default (shipped in Windows 11, installable on 10) and is
# the only one of the two that can be told a starting directory without a
# shell line, which is why it is preferred: `wt -d <dir>` needs no quoting
# of `dir` at all, because it is its own argv entry.
_WT = "wt.exe"
_CMD = "cmd.exe"


async def _spawn(argv: list[str]) -> tuple[bool, str]:
    """Start something and let it go. Never raises.

    These are launches, not jobs: `wt` and `explorer` return immediately
    having handed off to a window that outlives us, so the wait is only
    long enough to catch a spawn that failed outright.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
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


def _terminal_argv(cwd: str, command: str) -> list[str]:
    """The argv that opens a terminal at `cwd`, optionally running `command`.

    Isolated and pinned by tests because it is the quoting decision this
    whole interface exists for.

    With `wt`, `cwd` is its own argv entry (`-d <dir>`) and therefore needs
    no quoting whatever it contains. Only `command` reaches a shell, and it
    reaches cmd.exe's, not a POSIX one — its callers have already been
    through `builds.command_problem`, which permits no shell metacharacter
    at all, so there is nothing here to escape.

    Falling back to cmd.exe there is no such separation, so the directory
    does have to go into a shell line. `cd /d` handles a drive change,
    which a bare `cd` does not, and the path is wrapped in double quotes —
    cmd.exe has no escape character inside them, which is exactly why the
    path is checked by the caller before it ever gets here.
    """
    wt = shutil.which(_WT)
    if wt:
        argv = [wt]
        if cwd:
            argv += ["-d", cwd]
        if command:
            argv += ["cmd.exe", "/k", command]
        return argv

    cmd = shutil.which(_CMD) or _CMD
    if cwd and command:
        line = f'cd /d "{cwd}" && {command}'
    elif cwd:
        line = f'cd /d "{cwd}"'
    else:
        line = command
    return [cmd, "/k", line] if line else [cmd]


async def terminal(*, cwd: str = "", command: str = "") -> dict:
    """Open a terminal window at `cwd`, optionally running `command`."""
    ok, err = await _spawn(_terminal_argv(cwd, command))
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

    `code.cmd` is what the Windows installer puts on PATH, and a `.cmd`
    cannot be executed by `create_subprocess_exec` — that is the second
    half of the claude-path problem and the reason `shutil.which` is asked
    for the full name rather than being trusted to find `code`.
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
