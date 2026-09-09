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

CAP_SESSION_STEER was on that list until the roster was read on a real
machine. `messagingSocketPath` there carries a NAMED PIPE —
``\\\\.\\pipe\\LOCAL\\cc-msg-<hex>`` — rather than the AF_UNIX socket CPython
does not expose here, and `session_steer` writes its one JSON line to it with
the ordinary file API. So it is declared below.

What that proves is exactly what the macOS socket proves and no more: that
the bytes left this process. Neither platform reads a reply back, and the
`SENT` constant says so in both.

Everything portable — the run pipeline, memory, the dashboard, the
repository readers, the Playwright page tools, `github_repo`,
`usage_status` — works already and is not gated by any of this.
"""

from __future__ import annotations

from ..base import (CAP_BROWSER, CAP_EDITOR, CAP_NOTIFICATIONS,
                    CAP_SESSION_STEER, CAP_TERMINAL, Host)
from . import launcher, notifications, secrets

WINDOWS = Host(
    name="windows",
    capabilities=frozenset({
        CAP_NOTIFICATIONS,
        CAP_TERMINAL,
        CAP_BROWSER,
        CAP_EDITOR,
        CAP_SESSION_STEER,
    }),
    notifications=notifications,
    launcher=launcher,
    secrets=secrets,
)
