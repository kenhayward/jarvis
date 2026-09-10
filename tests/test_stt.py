"""Choosing where speech recognition happens.

`stt.py` is deliberately the same shape as `tts.py`: named backends, a
readiness map, and a fallback rather than a failure. The mouth already
learned these lessons and the ear should not learn them again.

Phase 4a ships this with `browser` as the default, so nothing about JARVIS
changes until a local backend exists and someone chooses it. See
docs/plans/phase-4-speech.md.

What 4-zero learned — that `webkitSpeechRecognition` is DEFINED inside
Electron and fails at runtime with `error=network` — is pinned in
`tests/frontend` territory rather than here, because the decision it drives
is made in `voice.ts` where the recogniser actually is. A Python mirror of it
would have no caller, and this project declares a thing in the same commit as
its implementation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# --- the backend names ----------------------------------------------------

def test_browser_is_the_default():
    """4a changes nothing observable. A user who does not opt in keeps the
    Chrome recogniser they have today."""
    import stt
    assert stt.DEFAULT_BACKEND == stt.BACKEND_BROWSER
    assert stt.resolve_backend() == stt.BACKEND_BROWSER


def test_the_env_var_chooses(monkeypatch):
    import stt
    monkeypatch.setenv("JARVIS_STT_BACKEND", stt.BACKEND_BROWSER)
    assert stt.resolve_backend() == stt.BACKEND_BROWSER


def test_an_explicit_argument_beats_the_environment(monkeypatch):
    import stt
    monkeypatch.setenv("JARVIS_STT_BACKEND", "nonsense")
    assert stt.resolve_backend(stt.BACKEND_BROWSER) == stt.BACKEND_BROWSER


def test_a_typo_falls_back_rather_than_going_deaf(monkeypatch):
    """`tts.py`'s rule, for the ear: "a typo in .env must not cost the user
    his voice". A typo here must not cost him his microphone either."""
    import stt
    monkeypatch.setenv("JARVIS_STT_BACKEND", "whsiper")
    assert stt.resolve_backend() == stt.DEFAULT_BACKEND


def test_case_and_whitespace_are_forgiven(monkeypatch):
    import stt
    monkeypatch.setenv("JARVIS_STT_BACKEND", "  BROWSER \n")
    assert stt.resolve_backend() == stt.BACKEND_BROWSER


# --- readiness ------------------------------------------------------------

def test_the_browser_backend_is_always_ready():
    """It needs nothing installed on this machine — the recogniser is in the
    page. Whether it WORKS where the page runs is a different question, and
    deliberately not one this module answers."""
    import stt
    assert stt.backends_ready()[stt.BACKEND_BROWSER] is True


def test_every_backend_has_a_readiness_answer():
    """A backend missing from the map would be offered in a dropdown with no
    way to know it cannot run — the trap `tts.backends_ready` exists for."""
    import stt
    assert set(stt.backends_ready()) == set(stt.BACKENDS)
