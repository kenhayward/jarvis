"""Both TTS backends, at their own seams.

`say` is never really spawned: the whole suite runs offline and silent, so
the subprocess boundary (`tts._spawn_say`) is faked here exactly as
`preflight._run_subprocess` and `dialog._osascript` are elsewhere. Fish is
faked at its httpx transport, as before.
"""
import json
import struct
import sys
from pathlib import Path

import httpx
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


def _fake_say(spawned: list, *, audio: bytes | None = None, error: str | None = None):
    """Stand in for `say`: record the invocation, write what it would have."""
    async def fake(argv, *, text, timeout):
        spawned.append({"argv": list(argv), "text": text, "timeout": timeout})
        if error is None:
            out = Path(argv[argv.index("-o") + 1])
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
async def test_say_returns_the_wav_it_wrote(monkeypatch):
    import tts
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.delenv("JARVIS_TTS_VOICE", raising=False)
    monkeypatch.delenv("JARVIS_TTS_RATE", raising=False)
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_say", _fake_say(spawned))

    r = await tts.synthesize_chunk("Good evening, sir.")

    assert r is not None and r.audio.startswith(b"RIFF") and r.audio[8:12] == b"WAVE"
    assert r.total_sec >= 0 and r.first_byte_sec == r.total_sec, "`say` cannot stream"
    argv = spawned[0]["argv"]
    assert argv[0] == "say"
    assert argv[argv.index("-v") + 1] == tts.DEFAULT_SAY_VOICE
    assert "--file-format=WAVE" in argv and f"--data-format=LEI16@{tts.SAY_SAMPLE_RATE}" in argv
    assert "-r" not in argv, "no rate configured means the voice's own"


@pytest.mark.asyncio
async def test_the_text_is_written_to_stdin_and_never_becomes_an_argument(monkeypatch):
    """A chunk is model-written and arrives through speech recognition. On the
    command line, one beginning with a dash would be read as flags."""
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_say", _fake_say(spawned))

    await tts.synthesize_chunk("-r 500 --voice Bogus, sir.", backend="say")

    assert spawned[0]["text"] == "-r 500 --voice Bogus, sir."
    assert "-r 500 --voice Bogus, sir." not in spawned[0]["argv"]
    assert spawned[0]["argv"][1:3] == ["-f", "-"], "text comes in on stdin"


@pytest.mark.asyncio
async def test_a_configured_voice_and_rate_reach_the_command(monkeypatch):
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_say", _fake_say(spawned))

    await tts.synthesize_chunk("x", backend="say", voice="Reed (English (UK))", rate=180)

    argv = spawned[0]["argv"]
    assert argv[argv.index("-v") + 1] == "Reed (English (UK))", "one argument, spaces and all"
    assert argv[argv.index("-r") + 1] == "180"


@pytest.mark.asyncio
async def test_the_working_file_is_gone_afterwards(monkeypatch):
    """Audio JARVIS speaks is never left on disk."""
    import tts
    spawned: list = []
    monkeypatch.setattr(tts, "_spawn_say", _fake_say(spawned))

    r = await tts.synthesize_chunk("x", backend="say")

    out = Path(spawned[0]["argv"][spawned[0]["argv"].index("-o") + 1])
    assert r is not None and not out.exists() and not out.parent.exists()


@pytest.mark.asyncio
async def test_a_failing_or_silent_say_is_one_lost_chunk_not_an_exception(monkeypatch):
    import tts
    monkeypatch.setattr(tts, "_spawn_say", _fake_say([], error="exit 1: no such voice"))
    assert await tts.synthesize_chunk("x", backend="say") is None

    monkeypatch.setattr(tts, "_spawn_say", _fake_say([], audio=b""))
    assert await tts.synthesize_chunk("x", backend="say") is None


@pytest.mark.asyncio
async def test_no_say_on_this_machine_returns_none(monkeypatch):
    """Everything else about JARVIS runs on macOS; this is the one place that
    can be told to use a hosted voice instead, so it must fail readably."""
    import tts
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)
    assert await tts.synthesize_chunk("x", backend="say") is None


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
async def test_fish_is_reached_only_by_asking_for_it(monkeypatch):
    """A key left in `.env` from before must not quietly start billing again."""
    import tts
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.setenv("FISH_API_KEY", "still-here")
    calls: list = []
    monkeypatch.setattr(tts, "_spawn_say", _fake_say([]))

    async with _client(lambda req: calls.append(1) or httpx.Response(200, content=b"x")) as c:
        r = await tts.synthesize_chunk("hello", api_key="still-here", voice_id="v", client=c)

    assert r is not None and r.audio.startswith(b"RIFF")
    assert calls == [], "nothing was sent to Fish Audio"


@pytest.mark.asyncio
async def test_non_200_returns_none():
    import tts
    async with _client(lambda req: httpx.Response(401, content=b"nope")) as c:
        assert await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c,
                                          backend="fish") is None


@pytest.mark.asyncio
async def test_transport_error_returns_none():
    import tts

    def boom(request):
        raise httpx.ConnectError("down")

    async with _client(boom) as c:
        assert await tts.synthesize_chunk("x", api_key="k", voice_id="v", client=c,
                                          backend="fish") is None


@pytest.mark.asyncio
async def test_empty_text_or_missing_key_short_circuits():
    import tts
    calls = []

    async with _client(lambda req: calls.append(1) or httpx.Response(200, content=b"x")) as c:
        assert await tts.synthesize_chunk("   ", api_key="k", voice_id="v", client=c,
                                          backend="fish") is None
        assert await tts.synthesize_chunk("hi", api_key="", voice_id="v", client=c,
                                          backend="fish") is None
    assert calls == []
