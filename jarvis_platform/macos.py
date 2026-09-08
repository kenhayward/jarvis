"""The Mac, which can do all of it.

Every capability is declared, so nothing is withdrawn and this file changes
no behaviour — which is the point while the platform layer is being put in.
The macOS implementations still live in `actions.py`, `screen.py`,
`notifier.py` and `dialog.py`; they move behind this host one module at a
time, and the capability set is what has to be true before any of them can.
"""

from __future__ import annotations

from .base import ALL_CAPABILITIES, Host

MACOS = Host(name="macos", capabilities=ALL_CAPABILITIES)
