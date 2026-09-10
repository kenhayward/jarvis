"""The `audio_in` frame: a page that captured an utterance itself.

Nothing here loads a model. `stt.transcribe` is the seam and it is faked, in
the pattern `tests/test_preflight.py` sets out — mock the one function, not
the library underneath it.

The property that matters most is at the bottom: audio and text reach exactly
the same place. `_final_transcript` was extracted so that the replay check,
the echo verdict and the fresh-start check cannot be implemented twice and
drift, and these tests are what would notice if somebody re-inlined one of
them.
"""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def srv(monkeypatch):
    import server
    import stt
    monkeypatch.setenv("JARVIS_STT_BACKEND", "whisper")

    heard = []

    async def fake_final(raw):
        heard.append(raw)

    monkeypatch.setattr(server, "_final_transcript", fake_final)
    return server, stt, heard


def _frame(data: bytes):
    return {"type": "audio_in", "data": base64.b64encode(data).decode()}


@pytest.mark.asyncio
async def test_audio_becomes_a_transcript(srv, monkeypatch):
    server, stt, heard = srv
    seen = {}

    async def fake_transcribe(audio, *, projects=None, model=None):
        seen["audio"] = audio
        seen["projects"] = projects
        return "cancel the chitauri run"

    monkeypatch.setattr(server.stt, "transcribe", fake_transcribe)
    await server._transcribe_audio_frame(_frame(b"RIFFxxxx"))
    assert seen["audio"] == b"RIFFxxxx"
    assert heard == ["cancel the chitauri run"]


@pytest.mark.asyncio
async def test_the_projects_are_offered_to_the_recogniser(srv, monkeypatch):
    """Measured worth 4/5 -> 5/5 on the words that reach tools as arguments.
    If this stops being passed, proper nouns quietly get worse and nothing
    fails."""
    server, stt, heard = srv
    seen = {}

    async def fake_transcribe(audio, *, projects=None, model=None):
        seen["projects"] = projects
        return "ok"

    monkeypatch.setattr(server, "_active_project_names", lambda: ["chitauri"])
    monkeypatch.setattr(server.stt, "transcribe", fake_transcribe)
    await server._transcribe_audio_frame(_frame(b"RIFF"))
    assert seen["projects"] == ["chitauri"]


@pytest.mark.asyncio
async def test_a_browser_backend_ignores_the_frame(srv, monkeypatch):
    """The default install. The page does not send this and the server has
    nothing to transcribe it with, so it is ignored rather than answered —
    "withdraw, never fake"."""
    server, stt, heard = srv
    monkeypatch.setenv("JARVIS_STT_BACKEND", "browser")
    called = []

    async def fake_transcribe(audio, **kw):
        called.append(audio)
        return "should never happen"

    monkeypatch.setattr(server.stt, "transcribe", fake_transcribe)
    await server._transcribe_audio_frame(_frame(b"RIFF"))
    assert called == [] and heard == []


@pytest.mark.asyncio
async def test_an_oversized_frame_is_refused_before_it_is_decoded(srv, monkeypatch):
    """A ceiling so a bad frame cannot make the server allocate without
    bound. Checked on the BASE64 length, before decoding — decoding first
    would allocate the thing the limit exists to prevent."""
    server, stt, heard = srv
    called = []
    monkeypatch.setattr(server.stt, "transcribe",
                        lambda *a, **k: called.append(1))
    huge = "A" * (server.MAX_AUDIO_FRAME_BYTES + 1)
    await server._transcribe_audio_frame({"type": "audio_in", "data": huge})
    assert called == [] and heard == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", 123, [], {"a": 1}, "not base64!!"])
async def test_a_malformed_frame_does_not_take_the_socket_down(srv, monkeypatch, bad):
    """This runs inside the WebSocket handler. Anything that raises here
    drops the user's connection mid-conversation, so every shape of rubbish
    has to be survivable."""
    server, stt, heard = srv

    async def fake_transcribe(audio, **kw):
        return "ok"

    monkeypatch.setattr(server.stt, "transcribe", fake_transcribe)
    await server._transcribe_audio_frame({"type": "audio_in", "data": bad})
    assert heard == []


@pytest.mark.asyncio
async def test_silence_is_not_announced(srv, monkeypatch):
    """An engine that heard nothing returns None, and nothing should reach
    the brain — not an empty turn, and not an apology."""
    server, stt, heard = srv

    async def fake_transcribe(audio, **kw):
        return None

    monkeypatch.setattr(server.stt, "transcribe", fake_transcribe)
    await server._transcribe_audio_frame(_frame(b"RIFF"))
    assert heard == []


# --- the property the extraction exists for -------------------------------

def test_both_routes_reach_the_same_handler():
    """Audio and text converge on `_final_transcript` and nothing else.

    Held against the source: if a future edit re-inlines the replay or echo
    logic into either branch, the two paths start to differ and the one that
    is not being used yet is the one that rots. That is the shape of half the
    defects this repository has found.
    """
    import ast
    src = Path(__file__).parent.parent / "server.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_final_transcript"]
    assert len(calls) >= 2, (
        "expected the text route and the audio route both to call "
        f"_final_transcript; found {len(calls)}")

    # And the verdict logic lives in exactly one place.
    owners = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "user_final"):
                    owners.add(node.name)
    assert owners == {"_final_transcript"}, (
        f"speech.user_final should be called from _final_transcript alone, "
        f"but is called from {sorted(owners)}")
