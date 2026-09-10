"""stt.py — where speech recognition happens.

The ear's version of `tts.py`, and deliberately the same shape: named
backends, a readiness map, and a fallback rather than a failure. The mouth
already learned those lessons; the ear should not learn them again.

**Phase 4a ships with `browser` as the default, so nothing changes.** The
recogniser is still Chrome's, in the page, exactly as it is today. This module
exists so that a local backend can be chosen later without the choice being
spread across `server.py` and `voice.ts` — see docs/plans/phase-4-speech.md.

**What is deliberately NOT here yet.** 4-zero measured, in a real Electron
renderer (Electron 44.3.0 / Chrome 152.0.7977.78):

    defined?          YES
    start() result:   ERROR event: error=network

`webkitSpeechRecognition` IS defined inside Electron. The constructor works,
`start()` succeeds, `onstart` fires, and only then does it fail — because
Chromium's speech service is a Google web service reached with keys only
Google's own builds carry.

So the obvious capability check, which `frontend/src/voice.ts:152` already
performs to pick its constructor:

    window.SpeechRecognition || window.webkitSpeechRecognition

reports that everything is fine in the one environment where it is not. A
decision about whether the browser can hear must rest on what happened when
somebody actually spoke, never on whether the API exists.

That rule lives in `frontend/src/voice.ts`, where the recogniser is and where
the decision is made, and NOT in a Python mirror of it here. A copy on this
side would have no caller — the server's `mic` frame is logged and drives
nothing by deliberate design — and this project's rule is that a capability
is declared in the same commit as its implementation, never before, or the
whole thing becomes a wish list. When a local backend exists and the server
has a reason to know, that is the commit to add it in.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("jarvis.stt")

BACKEND_BROWSER = "browser"
BACKENDS = (BACKEND_BROWSER,)
DEFAULT_BACKEND = BACKEND_BROWSER


def resolve_backend(backend: Optional[str] = None) -> str:
    """The backend to use: the argument, else JARVIS_STT_BACKEND, else browser.

    An unrecognised name falls back to the default rather than raising or
    going deaf. `tts.resolve_backend`'s reasoning, for the ear: a typo in
    `.env` must not cost the user his voice, and it must not cost him his
    microphone either.
    """
    name = (backend or os.getenv("JARVIS_STT_BACKEND")
            or DEFAULT_BACKEND).strip().lower()
    if name not in BACKENDS:
        log.warning(f"unknown JARVIS_STT_BACKEND {name!r}; "
                    f"using {DEFAULT_BACKEND!r}")
        return DEFAULT_BACKEND
    return name


def backends_ready() -> dict[str, bool]:
    """Which backends could actually run on this machine.

    `browser` is always True: the recogniser is in the page and this process
    installs nothing for it.

    Read that carefully, because it is a statement about THIS machine and not
    about whether the recogniser works where the page is running. Electron is
    exactly the case where those two answers differ — see the module
    docstring. Nothing here can answer the second question, and nothing here
    pretends to.
    """
    return {BACKEND_BROWSER: True}
