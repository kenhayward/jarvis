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

from dataclasses import dataclass


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


@dataclass(frozen=True)
class Host:
    """One platform, and what it can do.

    Intentionally only two fields for now. The sub-interfaces (notifications,
    screen, launcher, sessions) arrive as each module physically moves behind
    them; declaring protocols that nothing implements yet would be interface
    written against a guess rather than against code.
    """
    name: str
    capabilities: frozenset[str]

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
