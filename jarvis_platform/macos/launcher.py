"""macOS launching: a Terminal window, a browser, an editor.

Everything here drives AppleScript, and every script is composed here
rather than by the caller — including the `cd` the terminal needs. That
is not tidiness: quoting a path is a property of the shell you are
quoting FOR, and `shlex.quote` is POSIX. Leaving it at the call site
meant three copies of it in server.py, each of which would have to be
found and corrected for cmd.exe or PowerShell. One launcher owns its own
quoting.

Reached as `jarvis_platform.current().launcher`. Actions run IMMEDIATELY;
each returns {"success": bool, "confirmation": str}.
"""

import asyncio
import logging
import os
import shlex
import shutil

log = logging.getLogger("jarvis.platform.launcher")

async def _mark_terminal_as_jarvis(revert_after: float = 5.0):
    """Temporarily set the front Terminal window to Ocean theme, then revert.

    Shows the user JARVIS is active in that terminal. Reverts after revert_after seconds.
    """
    # Save the current profile, switch to Ocean, then revert
    script_save = (
        'tell application "Terminal"\n'
        '    return name of current settings of front window\n'
        'end tell'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script_save,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        original_profile = stdout.decode().strip()

        # Switch to Ocean
        script_set = (
            'tell application "Terminal"\n'
            '    set current settings of front window to settings set "Ocean"\n'
            'end tell'
        )
        proc2 = await asyncio.create_subprocess_exec(
            "osascript", "-e", script_set,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc2.communicate()

        # Schedule revert
        if original_profile and original_profile != "Ocean":
            asyncio.get_event_loop().call_later(
                revert_after,
                lambda: asyncio.ensure_future(_revert_terminal_theme(original_profile))
            )
    except Exception:
        pass


async def _revert_terminal_theme(profile_name: str):
    """Revert a Terminal window back to its original profile."""
    escaped = applescript_escape(profile_name)
    script = (
        'tell application "Terminal"\n'
        f'    set current settings of front window to settings set "{escaped}"\n'
        'end tell'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    except Exception:
        pass


def applescript_escape(s: str) -> str:
    """Escape a string for safe embedding in an AppleScript double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", " ")


async def terminal(*, cwd: str = "", command: str = "") -> dict:
    """Open Terminal.app at `cwd`, optionally running `command`. Marks it blue.

    The `cd` is composed here, not by the caller. `cwd` is quoted with
    `shlex.quote` because this is a POSIX shell; `command` is NOT, and must
    not be — a start command is meant to be a command. Its callers have
    already put it through `builds.command_problem`, which permits no shell
    metacharacter at all.
    """
    line = ""
    if cwd:
        line = f"cd {shlex.quote(cwd)}"
    if command:
        line = f"{line} && {command}" if line else command

    if line:
        escaped = applescript_escape(line)
        script = (
            'tell application "Terminal"\n'
            "    activate\n"
            f'    do script "{escaped}"\n'
            "end tell"
        )
    else:
        script = (
            'tell application "Terminal"\n'
            "    activate\n"
            "end tell"
        )
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    success = proc.returncode == 0
    if not success:
        log.error(f"terminal failed: {stderr.decode()}")
    else:
        await _mark_terminal_as_jarvis()
    return {
        "success": success,
        "confirmation": "Terminal is open, sir." if success else "I had trouble opening Terminal, sir.",
    }


async def browser(url: str, which: str = "chrome") -> dict:
    """Open URL in user's browser (Chrome or Firefox).

    The URL goes through `applescript_escape` and nothing else. A hand-rolled
    `.replace('"', ...)` lived here and escaped the quote but not the
    BACKSLASH, which is the half that matters: AppleScript reads `\\\\` as one
    literal backslash, so a URL ending `x\\"` closes the string literal and
    everything after it is code — and `do shell script` is in that language.
    The URL arrives from a model, out of speech, possibly echoing a page or a
    README, so this is a straight line from attacker text to a shell.
    `tests/test_applescript_url_injection.py` runs the payload.
    """
    escaped_url = applescript_escape(url)

    if which.lower() == "firefox":
        app_name = "Firefox"
        script = (
            'tell application "Firefox"\n'
            "    activate\n"
            f'    open location "{escaped_url}"\n'
            "end tell"
        )
    else:
        app_name = "Chrome"
        script = (
            'tell application "Google Chrome"\n'
            "    activate\n"
            f'    open location "{escaped_url}"\n'
            "end tell"
        )

    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    success = proc.returncode == 0
    if not success:
        log.error(f"browser ({app_name}) failed: {stderr.decode()}")
    return {
        "success": success,
        "confirmation": f"Pulled that up in {app_name}, sir." if success else f"{app_name} ran into a problem, sir.",
    }


# --- Opening code where the user actually reads it -----------------------
#
# The user's words: "maybe he should be able to open code files in VS Code or
# text editor." VS Code first when it is installed, the system default
# otherwise, so this still works on a Mac that has never had it.
#
# No AppleScript and no shell: `open` is exec'd with the path as its own argv
# entry, so a filename cannot be quoted out of a script the way it can out of
# an AppleScript string literal. Containment and the sensitive-file wall are
# the CALLER's job and have already run by the time this is reached — see
# server.tool_open_in_editor.

VSCODE_APP = "/Applications/Visual Studio Code.app"


def _vscode_command(path: str) -> list[str] | None:
    """The argv that opens `path` in VS Code, or None if it is not installed."""
    binary = shutil.which("code")
    if binary:
        return [binary, str(path)]
    if os.path.isdir(VSCODE_APP):
        return ["open", "-a", VSCODE_APP, str(path)]
    return None


async def editor(path: str) -> dict:
    """Open a file or directory in VS Code, else in the system default."""
    argv = _vscode_command(path)
    editor = "VS Code"
    if argv is None:
        argv = ["open", str(path)]
        editor = "your editor"

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        success = proc.returncode == 0
    except OSError as e:
        log.error(f"editor could not launch: {e}")
        return {"success": False, "editor": editor,
                "confirmation": "I couldn't open an editor, sir."}

    if not success:
        log.error(f"editor failed: {stderr.decode(errors='replace')}")
    return {
        "success": success,
        "editor": editor,
        "confirmation": f"Opened that in {editor}, sir." if success
        else f"{editor} wouldn't open that, sir.",
    }
