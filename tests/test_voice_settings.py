"""Choosing the voice from the settings panel.

The backend and both local voices are writable through `/api/settings/keys`,
which is a widening of the one endpoint that writes into `.env` — so what it
will and will not store is pinned here. `_write_env_key` also updates
`os.environ`, which is what makes a change take effect on JARVIS's next
sentence instead of his next restart.
"""
import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


# `_write_env_key` sets `os.environ[key]` — that is the whole point of it,
# and it is also a write monkeypatch never saw and will not undo. Without
# this, saving a voice here leaked JARVIS_PIPER_VOICE into every test that
# ran afterwards, and test_tts's piper tests failed in a full run while
# passing alone.
VOICE_ENV = ("JARVIS_TTS_BACKEND", "JARVIS_TTS_VOICE", "JARVIS_PIPER_VOICE",
             "FISH_API_KEY")


@pytest.fixture(autouse=True)
def _leave_the_environment_as_we_found_it():
    saved = {name: os.environ.get(name) for name in VOICE_ENV}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    for name in VOICE_ENV:
        monkeypatch.delenv(name, raising=False)

    import data_paths
    importlib.reload(data_paths)
    import run_store
    importlib.reload(run_store)
    import server
    importlib.reload(server)
    run_store.init_db()
    # Belt and braces: the reload re-runs server.py's own `.env` loader. It
    # honours JARVIS_ENV_FILE (which conftest points at a tmp file), but a
    # value already in os.environ would survive either way.
    for name in VOICE_ENV:
        monkeypatch.delenv(name, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(server, "_env_file_path", lambda: env_file)

    with TestClient(server.app,
                    headers={"Origin": "http://localhost:5173"}) as c:
        yield c, server


def _set(c, key, value):
    return c.post("/api/settings/keys", json={"key_name": key, "key_value": value})


def test_the_three_backends_are_settable(client):
    c, server = client
    for backend in ("say", "piper", "fish"):
        assert _set(c, "JARVIS_TTS_BACKEND", backend).status_code == 200, backend
    _, parsed = server._read_env()
    assert parsed["JARVIS_TTS_BACKEND"] == "fish"


def test_a_backend_jarvis_does_not_have_is_refused(client):
    """Anything else is silence — resolve_backend would fall back, but the
    panel must not be able to store a value that reads as a typo either."""
    c, server = client
    r = _set(c, "JARVIS_TTS_BACKEND", "elevenlabs")
    assert r.status_code == 400 and r.json()["success"] is False
    _, parsed = server._read_env()
    assert "JARVIS_TTS_BACKEND" not in parsed


def test_a_piper_voice_may_be_named_but_never_pathed(client):
    """onnxruntime executes the model it loads. Over HTTP this may only name
    one in the voices directory."""
    c, server = client
    assert _set(c, "JARVIS_PIPER_VOICE", "en_GB-alan-medium").status_code == 200
    for bad in ("/tmp/evil.onnx", "../../etc/passwd", "voices/x.onnx"):
        r = _set(c, "JARVIS_PIPER_VOICE", bad)
        assert r.status_code == 400, bad
        assert "not a path" in r.json()["error"], bad
    _, parsed = server._read_env()
    assert parsed["JARVIS_PIPER_VOICE"] == "en_GB-alan-medium"


def test_a_say_voice_keeps_its_spaces_and_brackets(client):
    """`say -v '?'` lists "Reed (English (UK))" — a real voice name, and one
    the .env round trip has to survive."""
    c, server = client
    assert _set(c, "JARVIS_TTS_VOICE", "Reed (English (UK))").status_code == 200
    _, parsed = server._read_env()
    assert parsed["JARVIS_TTS_VOICE"] == "Reed (English (UK))"


def test_saving_a_voice_takes_effect_without_a_restart(client):
    """The point of the panel: `_write_env_key` updates os.environ, and the
    resolvers read it per call, so the next sentence uses the new voice."""
    c, _ = client
    import tts
    assert tts.resolve_backend() == "say"
    _set(c, "JARVIS_TTS_BACKEND", "piper")
    _set(c, "JARVIS_PIPER_VOICE", "en_GB-northern_english_male-medium")
    assert tts.resolve_backend() == "piper"
    assert tts.resolve_piper_voice() == "en_GB-northern_english_male-medium"


def test_status_reports_the_voice_and_what_could_speak(client, tmp_path):
    c, _ = client
    import tts
    body = c.get("/api/settings/status").json()
    assert body["tts_backend"] == "say"
    assert body["tts_voice"] == tts.DEFAULT_SAY_VOICE
    assert body["tts_piper_voice"] == tts.DEFAULT_PIPER_VOICE
    assert set(body["tts_backends_ready"]) == {"say", "piper", "fish"}
    assert body["tts_backends_ready"]["fish"] is False, "no key, so not offerable"


def test_status_lists_the_models_actually_downloaded(client, tmp_path):
    """The panel offers these and nothing else: a name that is not on disk
    means JARVIS goes quiet mid-sentence, which is not a mistake he can
    report from inside a chunk."""
    c, _ = client
    assert c.get("/api/settings/status").json()["tts_piper_voices"] == []

    voices = tmp_path / "voices"
    voices.mkdir()
    for name in ("en_GB-southern_english_female-low", "en_GB-alan-medium"):
        (voices / f"{name}.onnx").write_bytes(b"onnx")
        (voices / f"{name}.onnx.json").write_text("{}")   # never listed itself

    body = c.get("/api/settings/status").json()
    assert body["tts_piper_voices"] == ["en_GB-alan-medium",
                                        "en_GB-southern_english_female-low"]


def test_the_placeholder_key_is_not_a_key(client):
    """`.env.example` ships FISH_API_KEY=your-fish-audio-api-key-here. Copying
    the template must not make the hosted backend look ready to go."""
    c, server = client
    _set(c, "FISH_API_KEY", server.FISH_KEY_PLACEHOLDER)
    body = c.get("/api/settings/status").json()
    assert body["env_keys_set"]["fish_audio"] is False
    assert body["tts_backends_ready"]["fish"] is False

    _set(c, "FISH_API_KEY", "a-real-looking-key")
    body = c.get("/api/settings/status").json()
    assert body["env_keys_set"]["fish_audio"] is True
    assert body["tts_backends_ready"]["fish"] is True


# --- and when it cannot speak, he says so -------------------------------------

class _FakeSpeech:
    def __init__(self):
        self.said: list[str] = []

    async def say(self, text, *args, **kwargs):
        self.said.append(text)

    async def stop(self):
        """The app's shutdown stops the mouth; a fake that cannot be stopped
        fails in teardown, after the test itself has passed."""

    def transport_gone(self):
        pass


@pytest.fixture
def fallen_back(monkeypatch):
    """A configured backend that never speaks, with `say` answering instead."""
    import server, tts
    monkeypatch.setenv("JARVIS_TTS_BACKEND", "piper")
    monkeypatch.setattr(server, "_voice_fallback", {"from": None})
    mouth = _FakeSpeech()
    monkeypatch.setattr(server, "speech", mouth)

    spoke_as = {"backend": tts.BACKEND_SAY}

    async def fake_synth(text, **kwargs):
        return tts.SynthResult(b"RIFF", 0.1, 0.1, backend=spoke_as["backend"])

    monkeypatch.setattr(tts, "synthesize_chunk", fake_synth)
    return server, mouth, spoke_as


@pytest.mark.asyncio
async def test_he_says_he_has_fallen_back_once_not_every_sentence(fallen_back):
    """Once is the whole trick: the notice is itself spoken through
    `_synth_for_speech`, so announcing before the flag is set would announce
    forever — and announcing per chunk would be worse than silence."""
    server, mouth, _ = fallen_back

    for _ in range(4):
        assert await server._synth_for_speech("Alpha one.") == b"RIFF"
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(mouth.said) == 1, mouth.said
    assert "Piper" in mouth.said[0] and "system voice" in mouth.said[0]
    assert server._voice_fallback["from"] == "piper"


@pytest.mark.asyncio
async def test_recovery_is_quiet_and_re_arms_the_notice(fallen_back):
    """Coming back is not news; going away again is."""
    server, mouth, spoke_as = fallen_back
    import tts

    await server._synth_for_speech("Alpha.")
    await asyncio.sleep(0)
    assert len(mouth.said) == 1

    spoke_as["backend"] = tts.BACKEND_PIPER            # the model turns up
    await server._synth_for_speech("Bravo.")
    assert server._voice_fallback["from"] is None
    assert len(mouth.said) == 1, "recovery is not announced"

    spoke_as["backend"] = tts.BACKEND_SAY              # and breaks again
    await server._synth_for_speech("Charlie.")
    await asyncio.sleep(0)
    assert len(mouth.said) == 2


@pytest.mark.asyncio
async def test_the_status_endpoint_shows_the_fallback(client, fallen_back):
    c, _ = client
    server, _, _ = fallen_back
    assert c.get("/api/settings/status").json()["tts_fallback_from"] is None
    await server._synth_for_speech("Alpha.")
    assert c.get("/api/settings/status").json()["tts_fallback_from"] == "piper"


def test_the_screen_switch_round_trips_through_the_settings_page(client):
    """The consent model is only real if the page can turn it OFF as easily
    as on, so the endpoint behind that checkbox is worth pinning.

    `screen_capture_gated` is a separate fact from `screen_capture`, and the
    page needs both: macOS gates capture through System Settings, so a toggle
    drawn there would be a switch JARVIS does not own and cannot honour.
    """
    import jarvis_platform as jp
    c, server = client
    body = c.get("/api/settings/status").json()

    gated = (jp.can(jp.CAP_SCREEN_CAPTURE)
             and jp.current().screen.CAPTURE_GATE.off_by_default)
    assert body["screen_capture_gated"] is gated
    assert body["screen_capture"] is False, "off is the shipped state"

    if not gated:
        return

    assert c.post("/api/settings/keys",
                  json={"key_name": "JARVIS_SCREEN_CAPTURE",
                        "key_value": "true"}).status_code == 200
    assert c.get("/api/settings/status").json()["screen_capture"] is True

    # And back off again, which is the half that matters most.
    assert c.post("/api/settings/keys",
                  json={"key_name": "JARVIS_SCREEN_CAPTURE",
                        "key_value": "false"}).status_code == 200
    assert c.get("/api/settings/status").json()["screen_capture"] is False

    # A spelling the switch itself would read as NO is refused rather than
    # stored, so the page can never show an eye open that is shut.
    assert c.post("/api/settings/keys",
                  json={"key_name": "JARVIS_SCREEN_CAPTURE",
                        "key_value": "on"}).status_code == 400


def test_no_startup_announcement_can_reach_the_voice(client):
    """The rail the test above needs, pinned where it was needed.

    `server._run_preflight` speaks whenever a check FAILS, and on a machine
    with no `say` the voice check does. It is fire-and-forget, and
    `TestClient` runs the app on its own thread, so that announcement is
    still in flight while these fixtures run on the main thread -- measured
    reaching `_synth_for_speech` twice, AFTER startup returned and after the
    first request. `fallen_back` sets JARVIS_TTS_BACKEND=piper and swaps in a
    fresh `_voice_fallback` dict, so the in-flight announcement could read
    the now-piper env, get `say` back, and write "piper" into that dict
    before the assertion above read it.

    It did: one Windows CI run failed on `assert 'piper' is None` and the
    next run of the SAME commit passed.

    `tests/conftest.py::_no_startup_announcement` closes it by emptying
    `preflight.spoken_summary`. This fails if that rail is removed, which is
    the only cheap way to notice -- the flake itself shows up perhaps once in
    a few hundred runs, and only where a check fails.
    """
    import preflight
    failing = [preflight.Check(name="voice", status=preflight.STATUS_FAIL,
                               message="no voice", remedy="install one")]
    assert preflight.spoken_summary(failing) == "", \
        "the startup announcement rail is not installed"
