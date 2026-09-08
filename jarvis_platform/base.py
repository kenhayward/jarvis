"""What a platform can do, and which tools depend on it.

JARVIS drives the machine it runs on, so a second platform is not a matter
of translating each subprocess — some of what he does has no equivalent
elsewhere, and some has one that has not been built yet. This module is how
that is stated, once, rather than discovered by a tool failing.

The rule, and it is the reason this is a set of capabilities rather than a
set of try/excepts: **a platform that cannot do something withdraws the
tool, it does not fake it.** A tool that always answers "not supported on
this platform" is described to the brain on every single turn at roughly
250 tokens, invites it to try anyway, and gives it something to apologise
for. A tool the brain never sees costs nothing and cannot be misused.

Capabilities are deliberately named after the *behaviour*, not the module
or the API. `screen_capture` is a thing JARVIS can or cannot do;
`screencapture` is how one platform happens to do it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("jarvis.platform")


# --- the capabilities ------------------------------------------------------

#: Put a picture of the user's screen in front of the brain.
CAP_SCREEN_CAPTURE = "screen_capture"
#: Read which windows are open and which application is in front.
CAP_WINDOW_LIST = "window_list"
#: Open a visible terminal window at a directory, optionally running something.
CAP_TERMINAL = "terminal"
#: Open a URL or a local file in the user's browser.
CAP_BROWSER = "browser"
#: Open a file or directory in the user's editor.
CAP_EDITOR = "editor"
#: Send one keystroke to the terminal a specific Claude Code session runs in.
CAP_DIALOG_KEY = "dialog_key"
#: Post a message into another Claude Code session's inbox.
CAP_SESSION_STEER = "session_steer"
#: Post a native notification when no browser tab is listening.
CAP_NOTIFICATIONS = "notifications"

ALL_CAPABILITIES = frozenset({
    CAP_SCREEN_CAPTURE,
    CAP_WINDOW_LIST,
    CAP_TERMINAL,
    CAP_BROWSER,
    CAP_EDITOR,
    CAP_DIALOG_KEY,
    CAP_SESSION_STEER,
    CAP_NOTIFICATIONS,
})


# --- which tools need which ------------------------------------------------
#
# Only the tools that depend on a platform capability appear here. Everything
# absent is portable and is never withdrawn: the run pipeline, the memory
# writers, the repository readers, the Playwright page tools, `github_repo`,
# `usage_status`, `connections`, `list_sessions` and the rest all work
# anywhere Python does.
#
# `run_command` shares CAP_TERMINAL with `open_in_terminal` because it is
# the same act — it opens a Terminal window and types a command into it
# (server.py's `_perform_run_command`), it does not run anything itself.

TOOL_CAPABILITIES: dict[str, str] = {
    "look_at_screen": CAP_SCREEN_CAPTURE,
    "what_is_on_screen": CAP_WINDOW_LIST,
    "open_in_terminal": CAP_TERMINAL,
    "run_command": CAP_TERMINAL,
    "open_in_browser": CAP_BROWSER,
    "open_in_editor": CAP_EDITOR,
    "answer_dialog": CAP_DIALOG_KEY,
    "steer_session": CAP_SESSION_STEER,
}


# --- the sub-interfaces ----------------------------------------------------
#
# One per module as it physically moves behind the layer. A protocol written
# before its implementation would be an interface designed against a guess,
# so this list grows with `jarvis_platform/macos/` rather than ahead of it.


class Notifications(Protocol):
    """Getting the user's attention when nothing is listening on the voice
    channel. Implementations must never raise — see the macOS one."""

    def available(self) -> bool: ...

    async def notify(self, title: str, message: str, *,
                     subtitle: str = "") -> bool: ...


class _NoNotifications:
    """The answer on a platform whose notifications have not been built.

    Exactly what the macOS implementation already did when it found itself
    somewhere else: say so once in the log, report False, and never raise.
    The announcement path treats False as "nobody was told", which is true.
    """

    def available(self) -> bool:
        return False

    async def notify(self, title: str, message: str, *,
                     subtitle: str = "") -> bool:
        log.warning("notifications are not available on this platform")
        return False


NO_NOTIFICATIONS = _NoNotifications()


class Launcher(Protocol):
    """Putting something on the user's screen: a terminal, a page, a file.

    Each returns `{"success": bool, "confirmation": str}` — `confirmation`
    is a sentence fit to be spoken, because it usually is. `editor` also
    returns `"editor"`, the name of what actually opened.

    `terminal` takes `cwd` and `command` separately rather than a composed
    shell line, so the implementation can quote for its own shell. That is
    the whole reason this is an interface and not three free functions.
    """

    async def terminal(self, *, cwd: str = "", command: str = "") -> dict: ...

    async def browser(self, url: str, which: str = "chrome") -> dict: ...

    async def editor(self, path: str) -> dict: ...


class _NoLauncher:
    """A platform that cannot open windows yet.

    Unreachable in practice — every tool that calls a launcher is withdrawn
    by CAP_TERMINAL / CAP_BROWSER / CAP_EDITOR before it can be invoked, so
    this is the backstop behind that gate rather than the gate itself. It
    refuses in the shape callers already handle: `success` False and a
    sentence, never an exception.
    """

    _REFUSAL = {"success": False,
                "confirmation": "I can't open that on this machine, sir."}

    async def terminal(self, *, cwd: str = "", command: str = "") -> dict:
        return dict(self._REFUSAL)

    async def browser(self, url: str, which: str = "chrome") -> dict:
        return dict(self._REFUSAL)

    async def editor(self, path: str) -> dict:
        return dict(self._REFUSAL, editor="an editor")


NO_LAUNCHER = _NoLauncher()


@dataclass(frozen=True)
class Host:
    """One platform, what it can do, and how it does it.

    The sub-interface fields default to null objects so that an unknown
    platform is constructible and JARVIS still starts on it. That is the
    same choice `capabilities` makes: claim nothing, refuse cleanly, and
    let the portable two thirds of him work.
    """
    name: str
    capabilities: frozenset[str]
    notifications: Notifications = field(default=NO_NOTIFICATIONS)
    launcher: Launcher = field(default=NO_LAUNCHER)

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def allows_tool(self, tool: str) -> bool:
        """Whether this platform can run `tool` at all.

        A tool with no entry in TOOL_CAPABILITIES is portable, and portable
        is the default — a new tool has to opt IN to being platform-bound,
        so forgetting to list one leaves it working everywhere rather than
        silently disabled on the platform nobody tested.
        """
        needed = TOOL_CAPABILITIES.get(tool)
        return needed is None or needed in self.capabilities

    def withdrawn_tools(self) -> frozenset[str]:
        """Every tool this platform cannot offer. Empty on a complete host."""
        return frozenset(name for name, cap in TOOL_CAPABILITIES.items()
                         if cap not in self.capabilities)

    def filter_tools(self, names):
        """`names`, minus anything this platform cannot do, order preserved."""
        return [n for n in names if self.allows_tool(n)]
