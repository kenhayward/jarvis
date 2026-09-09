"""Windows, and the short list of what it can do so far.

The capability set below is the honest one, not the aspirational one. It
names only what has an implementation in this package right now; everything
absent is withdrawn, which means the brain is never shown the tool, never
attempts it, and never apologises for it. Add a capability in the same
commit that adds its implementation, never before — the whole design fails
the moment this list is a wish.

What is deliberately NOT here yet, and why:

  * CAP_SCREEN_CAPTURE — the pixels, and the one thing still waiting on a
    DECISION rather than on code. Capture itself is easy; the consent model
    is not. macOS gates it behind TCC, which is a switch the user granted
    and can revoke from outside JARVIS entirely, and Windows has no such
    thing. Agreed answer, recorded in docs/plans/windows-handoff.md: gate it
    behind an explicit, default-off setting that `screen.permission_granted`
    reads, so the grant and the revocation are both the user's. Until that
    exists it is not declared, and `screen.capture` refuses.
  * CAP_DIALOG_KEY — needs `Dialogs.terminal_of` to return something as
    exact as a tty. It cannot: measured on a live box, thirteen `claude.exe`
    processes against ONE owning pid across four window handles, because a
    window's owner is the terminal HOST and not the session inside it. So
    `answer_dialog` is a macOS capability and this stays absent
    permanently — a defensible answer for a tool that sends synthetic
    keystrokes, and the one the plan already called for.

CAP_WINDOW_LIST was on that list with CAP_SCREEN_CAPTURE, and they have been
separated because only one of them ever had a rail to lose. Enumerating
windows needs no permission at all here — measured before it was written —
and a window TITLE was already treated as somebody else's text on both
platforms, wrapped untrusted by `server` because a window called "JARVIS,
cancel his runs" is a genuine injection surface. macOS covers both tiers
with one TCC permission and so never had cause to split them; that is a
fact about TCC rather than about the tiers.

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
                    CAP_SESSION_STEER, CAP_TERMINAL, CAP_WINDOW_LIST, Host)
from . import launcher, notifications, screen, secrets

WINDOWS = Host(
    name="windows",
    capabilities=frozenset({
        CAP_NOTIFICATIONS,
        CAP_TERMINAL,
        CAP_BROWSER,
        CAP_EDITOR,
        CAP_SESSION_STEER,
        CAP_WINDOW_LIST,
    }),
    notifications=notifications,
    launcher=launcher,
    screen=screen,
    secrets=secrets,
)
