"""Windows, and the short list of what it can do so far.

The capability set below is the honest one, not the aspirational one. It
names only what has an implementation in this package right now; everything
absent is withdrawn, which means the brain is never shown the tool, never
attempts it, and never apologises for it. Add a capability in the same
commit that adds its implementation, never before — the whole design fails
the moment this list is a wish.

What is deliberately NOT here yet, and why:

  * CAP_SCREEN_CAPTURE / CAP_WINDOW_LIST — needs a capture route decided
    (GDI through ctypes, or the `mss` package) and, more importantly, needs
    the consent model the platform review called for. macOS gates these
    behind TCC; Windows asks nobody, so shipping them unchanged would
    remove a safety rail the design leans on rather than port it.
  * CAP_DIALOG_KEY — needs `Dialogs.terminal_of` to return something as
    exact as a tty. If it cannot, `answer_dialog` is a macOS capability and
    this stays absent permanently, which is a defensible answer for a tool
    that sends synthetic keystrokes.
  * CAP_SESSION_STEER — `socket.AF_UNIX` is not exposed by CPython here.
    Claude Code on Windows most likely publishes a named pipe instead, but
    the roster's `socket_path` has to be READ on a real machine before
    anything is written against it.

Everything portable — the run pipeline, memory, the dashboard, the
repository readers, the Playwright page tools, `github_repo`,
`usage_status` — works already and is not gated by any of this.
"""

from __future__ import annotations

from ..base import (CAP_BROWSER, CAP_EDITOR, CAP_NOTIFICATIONS, CAP_TERMINAL,
                    Host)
from . import launcher, notifications, secrets

WINDOWS = Host(
    name="windows",
    capabilities=frozenset({
        CAP_NOTIFICATIONS,
        CAP_TERMINAL,
        CAP_BROWSER,
        CAP_EDITOR,
    }),
    notifications=notifications,
    launcher=launcher,
    secrets=secrets,
)
