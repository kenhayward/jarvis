"""The Mac, which can do all of it.

Every capability is declared, so nothing is withdrawn and this host changes
no behaviour — which is the point while the platform layer is being put in.

The implementations move here one module at a time. Each arrives as a
MODULE exposed as the host's provider, not as a class instance, and that is
deliberate: the test suite already patches these seams on the module object
(`monkeypatch.setattr(notifications, "notify", ...)`) precisely so that the
`importlib.reload(server)` several fixtures do cannot hand the real
implementation back. Keeping them modules keeps that working.

All four are here now: notifications, launcher, dialogs, screen.
"""

from __future__ import annotations

from ..base import ALL_CAPABILITIES, Host
from . import dialogs, launcher, notifications, screen

MACOS = Host(
    name="macos",
    capabilities=ALL_CAPABILITIES,
    notifications=notifications,
    launcher=launcher,
    dialogs=dialogs,
    screen=screen,
)
