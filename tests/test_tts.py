"""All three TTS backends, at their own seams.

Neither local synthesiser is ever really spawned: the whole suite runs
offline and silent, so the subprocess boundary (`tts._spawn_synth`) is faked
here exactly as `preflight._run_subprocess` and `dialog._osascript` are
elsewhere. Fish is faked at its httpx transport, as before.
"""
import json
import struct
import sys
from pathlib import Path

import httpx
import os
import shutil
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _wav(seconds: float = 0.5, rate: int = 22050) -> bytes:
    body = bytes(int(seconds * rate) * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", len(body)) + body)
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


@pytest.fixture
def say_on_path(monkeypatch):
    """Make `say` resolvable, without pretending anything else is.

    The tests that use this are about the `say` backend's own logic — the
    argv it builds, that the text goes to STDIN and never becomes an
    argument, that the working file is removed, that a failing backend hands
    over. All of that is ordinary Python and runs anywhere. What does not is
    `_synthesize_say`'s first line, a `shutil.which("say")` guard that
    returns None off macOS and bails before any of it.

    So the binary is a PRECONDITION here, not the behaviour under test, and
    faking it is the same move as the faked `_spawn_synth` beside it —
    nothing is ever executed either way. Narrow on purpose: only `say`
    answers, so a piper or fish lookup in the same test stays honest, and
    the test that asserts the MISSING-say path keeps its own `which -> None`.
    """
    import tts
    real = tts.shutil.which
    monkeypatch.setattr(
        tts.shutil, "which",
        lambda name: "/usr/bin/say" if name == "say" else real(name))


def _fake_spawn(spawned: list, *, audio: bytes | None = None, error: str | None = None):
    """Stand in for a local synthesiser: record the invocation, write what it
    would have. `say` names its output with -o, piper with -f."""
    async def fake(argv, *, text, timeout):
        spawned.append({"argv": list(argv), "text": text, "timeout": timeout})
        if error is None:
            flag = "-o" if "-o" in argv else "-f"
            out = Path(argv[argv.index(flag) + 1])
            out.write_bytes(_wav() if audio is None else audio)
        return error
    return fake


# --- which backend ------------------------------------------------------------

def test_local_say_is_the_default_and_the_env_var_chooses(monkeypatch):
    import tts
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    assert tts.resolve_backend() == tts.BACKEND_SAY
    monkeypatch.setenv("JARVIS_TTS_BACKEND", "fish")
    assert tts.resolve_backend() == tts.BACKEND_FISH
    monkeypatch.setenv("JARVIS_TTS_BACKEND", "piper")
    assert tts.resolve_backend() == tts.BACKEND_PIPER
    assert tts.resolve_backend("say") == tts.BACKEND_SAY, "an argument beats the env"


def test_a_typo_in_the_backend_still_leaves_him_a_voice(monkeypatch):
    """A misspelled backend must not be silence: it falls back and says so."""
    import tts
    monkeypatch.setenv("JARVIS_TTS_BACKEND", "fsh")
    assert tts.resolve_backend() == tts.BACKEND_SAY


def test_voice_and_rate_come_from_the_environment(monkeypatch):
    import tts
    monkeypatch.delenv("JARVIS_TTS_VOICE", raising=False)
    monkeypatch.delenv("JARVIS_TTS_RATE", raising=False)
    assert tts.resolve_voice() == tts.DEFAULT_SAY_VOICE and tts.resolve_rate() == 0
    monkeypatch.setenv("JARVIS_TTS_VOICE", "Reed (English (UK))")
    monkeypatch.setenv("JARVIS_TTS_RATE", "180")
    assert tts.resolve_voice() == "Reed (English (UK))" and tts.resolve_rate() == 180
    monkeypatch.setenv("JARVIS_TTS_RATE", "not a number")
    assert tts.resolve_rate() == 0, "a bad rate is the voice's own default, not a crash"


# --- the local backend --------------------------------------------------------

@pytest.mark.asyncio
async def test_say_returns_the_wav_it_wrote(monkeypatch, say_on_path):
    import tts
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.delenv("JARVIS_TTS_VOICE", raising=False)
    monkeypatch.delenv("JARVIS_TTS_RATE", raising=False)
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    r = await tts.synthesize_chunk("Good evening, sir.")

    assert r is not None and r.audio.startswith(b"RIFF") and r.audio[8:12] == b"WAVE"
    assert r.total_sec >= 0 and r.first_byte_sec == r.total_sec, "`say` cannot stream"
    argv = spawned[0]["argv"]
    assert argv[0] == "say"
    assert argv[argv.index("-v") + 1] == tts.DEFAULT_SAY_VOICE
    assert "--file-format=WAVE" in argv and f"--data-format=LEI16@{tts.SAY_SAMPLE_RATE}" in argv
    assert "-r" not in argv, "no rate configured means the voice's own"


@pytest.mark.asyncio
async def test_the_text_is_written_to_stdin_and_never_becomes_an_argument(monkeypatch, say_on_path):
    """A chunk is model-written and arrives through speech recognition. On the
    command line, one beginning with a dash would be read as flags."""
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    await tts.synthesize_chunk("-r 500 --voice Bogus, sir.", backend="say")

    assert spawned[0]["text"] == "-r 500 --voice Bogus, sir."
    assert "-r 500 --voice Bogus, sir." not in spawned[0]["argv"]
    assert spawned[0]["argv"][1:3] == ["-f", "-"], "text comes in on stdin"


@pytest.mark.asyncio
async def test_a_configured_voice_and_rate_reach_the_command(monkeypatch, say_on_path):
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    await tts.synthesize_chunk("x", backend="say", voice="Reed (English (UK))", rate=180)

    argv = spawned[0]["argv"]
    assert argv[argv.index("-v") + 1] == "Reed (English (UK))", "one argument, spaces and all"
    assert argv[argv.index("-r") + 1] == "180"


@pytest.mark.asyncio
async def test_the_working_file_is_gone_afterwards(monkeypatch, say_on_path):
    """Audio JARVIS speaks is never left on disk."""
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    r = await tts.synthesize_chunk("x", backend="say")

    out = Path(spawned[0]["argv"][spawned[0]["argv"].index("-o") + 1])
    assert r is not None and not out.exists() and not out.parent.exists()


@pytest.mark.asyncio
async def test_a_failing_or_silent_say_is_one_lost_chunk_not_an_exception(monkeypatch):
    import tts
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn([], error="exit 1: no such voice"))
    assert await tts.synthesize_chunk("x", backend="say") is None

    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn([], audio=b""))
    assert await tts.synthesize_chunk("x", backend="say") is None


@pytest.mark.asyncio
async def test_no_say_on_this_machine_returns_none(monkeypatch):
    """Everything else about JARVIS runs on macOS; this is the one place that
    can be told to use a hosted voice instead, so it must fail readably."""
    import tts
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)
    assert await tts.synthesize_chunk("x", backend="say") is None


# --- the piper backend --------------------------------------------------------

def test_piper_is_looked_for_beside_the_interpreter_first(monkeypatch, tmp_path):
    """Measured, not theoretical: the server runs as `.venv/bin/python
    server.py` WITHOUT the venv activated, so `which piper` returns None while
    `.venv/bin/piper` sits right there."""
    import tts
    monkeypatch.delenv("JARVIS_PIPER_BIN", raising=False)
    fake_bin = tmp_path / "piper"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(tts.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)
    assert tts.piper_bin() == str(fake_bin)

    fake_bin.unlink()
    assert tts.piper_bin() is None, "and nothing on PATH means nothing"
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/piper")
    assert tts.piper_bin() == "/usr/local/bin/piper", "PATH is still the fallback"


def test_a_piper_voice_is_a_model_in_the_voices_directory(monkeypatch, tmp_path):
    import tts
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JARVIS_PIPER_VOICE", raising=False)
    assert tts.resolve_piper_voice() == tts.DEFAULT_PIPER_VOICE
    assert tts.piper_model_path() is None, "nothing downloaded yet"

    voices = tmp_path / "voices"
    voices.mkdir()
    model = voices / f"{tts.DEFAULT_PIPER_VOICE}.onnx"
    model.write_bytes(b"onnx")
    assert tts.piper_model_path() == model

    # A hand-edited .env may still name a path outright.
    elsewhere = tmp_path / "elsewhere.onnx"
    elsewhere.write_bytes(b"onnx")
    monkeypatch.setenv("JARVIS_PIPER_VOICE", str(elsewhere))
    assert tts.piper_model_path() == elsewhere


def test_a_settable_voice_name_may_not_be_a_path():
    """`JARVIS_PIPER_VOICE` is writable over HTTP, and onnxruntime executes
    what it loads. A name resolves inside the voices directory; a path does
    not get to arrive through a POST."""
    import tts
    assert tts.is_safe_voice_name("en_GB-alan-medium")
    assert not tts.is_safe_voice_name("../../etc/passwd")
    assert not tts.is_safe_voice_name("/tmp/evil.onnx")
    assert not tts.is_safe_voice_name("")
    # `$` matches before a trailing newline, so this is what an anchored
    # pattern gated with `.match` would have waved through.
    assert not tts.is_safe_voice_name("en_GB-alan-medium\n")
    assert not tts.is_safe_voice_name("alan\nJARVIS_CLAUDE_PATH=/tmp/evil")


@pytest.mark.asyncio
async def test_piper_renders_a_wav_with_the_model_it_resolved(monkeypatch, tmp_path):
    import tts
    voices = tmp_path / "voices"
    voices.mkdir()
    model = voices / "en_GB-alan-medium.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JARVIS_PIPER_VOICE", raising=False)
    monkeypatch.setattr(tts, "piper_bin", lambda: "/opt/piper")
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    r = await tts.synthesize_chunk("Good evening, sir.", backend="piper")

    assert r is not None and r.audio.startswith(b"RIFF")
    argv = spawned[0]["argv"]
    assert argv[0] == "/opt/piper"
    assert argv[argv.index("-m") + 1] == str(model)
    assert spawned[0]["text"] == "Good evening, sir.", "on stdin, as with `say`"


@pytest.mark.asyncio
async def test_piper_declines_without_its_binary_or_its_model(monkeypatch, tmp_path):
    """Both are ordinary states — an optional dependency and a 63 MB download —
    so the backend declines and logs a remedy rather than raising. What the
    user then HEARS is `say`; that is the next test."""
    import tts
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tts, "piper_bin", lambda: None)
    assert await tts.synthesize_chunk("x", backend="piper", fallback=False) is None

    monkeypatch.setattr(tts, "piper_bin", lambda: "/opt/piper")
    assert await tts.synthesize_chunk("x", backend="piper", fallback=False) is None, "no model"


def test_backends_ready_reports_what_could_actually_speak(monkeypatch, tmp_path):
    import tts
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/bin/say")
    monkeypatch.setattr(tts, "piper_bin", lambda: None)
    ready = tts.backends_ready()
    assert ready == {"say": True, "piper": False, "fish": False}

    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / f"{tts.DEFAULT_PIPER_VOICE}.onnx").write_bytes(b"onnx")
    monkeypatch.delenv("JARVIS_PIPER_VOICE", raising=False)
    monkeypatch.setattr(tts, "piper_bin", lambda: "/opt/piper")
    assert tts.backends_ready(fish_key="k") == {"say": True, "piper": True, "fish": True}


# --- falling back rather than going quiet --------------------------------------

@pytest.mark.asyncio
async def test_a_backend_that_cannot_speak_hands_over_to_say(monkeypatch, tmp_path, say_on_path):
    """Silence is the worst failure JARVIS has: a voice assistant that has
    gone quiet looks broken, not misconfigured. `say` needs nothing, so it
    takes over — and the result says who really spoke."""
    import tts
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))       # no piper model
    monkeypatch.setattr(tts, "piper_bin", lambda: "/opt/piper")
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    r = await tts.synthesize_chunk("Good evening, sir.", backend="piper")

    assert r is not None and r.backend == tts.BACKEND_SAY
    assert spawned and spawned[0]["argv"][0] == "say", "piper never ran; say did"


@pytest.mark.asyncio
async def test_the_hosted_backend_falls_back_too(monkeypatch, say_on_path):
    """A network that is down should cost the voice, not the assistant."""
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn(spawned))

    def boom(request):
        raise httpx.ConnectError("down")

    async with _client(boom) as c:
        r = await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c,
                                       backend="fish")
    assert r is not None and r.backend == tts.BACKEND_SAY


@pytest.mark.asyncio
async def test_a_working_backend_is_never_labelled_a_fallback(monkeypatch, tmp_path):
    import tts
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "en_GB-alan-medium.onnx").write_bytes(b"onnx")
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_PIPER_VOICE", "en_GB-alan-medium")
    monkeypatch.setattr(tts, "piper_bin", lambda: "/opt/piper")
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn([]))

    r = await tts.synthesize_chunk("x", backend="piper")
    assert r is not None and r.backend == tts.BACKEND_PIPER


@pytest.mark.asyncio
async def test_when_say_cannot_speak_either_there_is_nothing_left(monkeypatch, tmp_path):
    """None means macOS itself would not speak — the scheduler's cue to fall
    back on text, which is the last honest option."""
    import tts
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tts, "piper_bin", lambda: None)
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)
    assert await tts.synthesize_chunk("x", backend="piper") is None


@pytest.mark.asyncio
async def test_fallback_can_be_switched_off(monkeypatch, tmp_path):
    import tts
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tts, "piper_bin", lambda: None)
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn([]))
    assert await tts.synthesize_chunk("x", backend="piper", fallback=False) is None


# --- the hosted backend -------------------------------------------------------

@pytest.mark.asyncio
async def test_sends_balanced_latency_and_assembles_stream():
    import tts
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3" + b"\x00" * 100)

    async with _client(handler) as c:
        r = await tts.synthesize_chunk("Good evening, sir.", api_key="k", voice_id="v",
                                       client=c, backend="fish")
    assert seen["url"] == tts.FISH_TTS_URL
    assert seen["auth"] == "Bearer k"
    assert seen["body"] == {"text": "Good evening, sir.", "reference_id": "v",
                            "format": "mp3", "mp3_bitrate": 128, "latency": "balanced"}
    assert r is not None and r.audio.startswith(b"ID3") and len(r.audio) == 103
    assert r.first_byte_sec >= 0 and r.total_sec >= r.first_byte_sec


@pytest.mark.asyncio
async def test_fish_is_reached_only_by_asking_for_it(monkeypatch, say_on_path):
    """A key left in `.env` from before must not quietly start billing again."""
    import tts
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.setenv("FISH_API_KEY", "still-here")
    calls: list = []
    monkeypatch.setattr(tts, "_spawn_synth", _fake_spawn([]))

    async with _client(lambda req: calls.append(1) or httpx.Response(200, content=b"x")) as c:
        r = await tts.synthesize_chunk("hello", api_key="still-here", voice_id="v", client=c)

    assert r is not None and r.audio.startswith(b"RIFF")
    assert calls == [], "nothing was sent to Fish Audio"


@pytest.mark.asyncio
async def test_non_200_returns_none():
    """`fallback=False` throughout this section: these test the hosted backend
    itself, not the `say` safety net underneath it."""
    import tts
    async with _client(lambda req: httpx.Response(401, content=b"nope")) as c:
        assert await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c,
                                          backend="fish", fallback=False) is None


@pytest.mark.asyncio
async def test_transport_error_returns_none():
    import tts

    def boom(request):
        raise httpx.ConnectError("down")

    async with _client(boom) as c:
        assert await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c,
                                          backend="fish", fallback=False) is None


@pytest.mark.asyncio
async def test_empty_text_or_missing_key_short_circuits():
    import tts
    calls = []

    async with _client(lambda req: calls.append(1) or httpx.Response(200, content=b"x")) as c:
        assert await tts.synthesize_chunk("   ", api_key="k", voice_id="v", client=c,
                                          backend="fish", fallback=False) is None
        assert await tts.synthesize_chunk("hi", api_key="", voice_id="v", client=c,
                                          backend="fish", fallback=False) is None
    assert calls == []


# --- finding piper on the platform pip installed it for --------------------


def test_piper_is_found_beside_the_interpreter_that_installed_it(tmp_path, monkeypatch):
    r"""The console script `pip install piper-tts` writes for THIS interpreter,
    whatever this platform calls it.

    On POSIX that is `piper`; on Windows it is `piper.exe`, and looking for a
    bare `piper` there finds nothing. The fallback cannot save it either:
    `.venv\Scripts` is not on PATH — which is the entire reason this function
    looks beside `sys.executable` in the first place — so `which("piper")`
    returns None too.

    Measured 2026-09-10 on a real Windows box with piper correctly installed
    and its voice downloaded: `piper_bin()` returned None, `backends_ready()`
    reported piper unavailable, and JARVIS was mute on a platform that has no
    `say` to fall back to.
    """
    import tts
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    name = "piper.exe" if os.name == "nt" else "piper"
    binary = scripts / name
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    monkeypatch.delenv("JARVIS_PIPER_BIN", raising=False)
    monkeypatch.setattr(tts.sys, "executable", str(scripts / "python.exe"))
    # Nothing on PATH, so only the beside-the-interpreter lookup can win.
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)

    found = tts.piper_bin()
    assert found is not None, (
        f"pip installed {name!r} beside the interpreter and piper_bin() "
        f"could not see it")
    assert Path(found).name == name
