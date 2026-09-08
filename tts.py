"""
tts.py — one sentence chunk in, one complete audio blob out.

Two backends behind one call:

    say    macOS's own synthesiser, and the default. Offline, no key, no
           dependency, nothing to bill. Measured on this project's Mac with
           the en_GB voice Daniel: ~0.45s per sentence whatever its length —
           the cost is process startup, not synthesis — against 1.2-3.5s of
           audio, so it stays comfortably ahead of the mouth.
    fish   Fish Audio, the original hosted voice. Needs FISH_API_KEY, and is
           reached only by asking for it: JARVIS_TTS_BACKEND=fish.

The Fish response is streamed so time-to-first-byte can be measured. `say`
cannot stream at all — it seeks its output file to write the WAV header, so
`-o -` yields zero bytes (measured) — so its `first_byte_sec` IS its total.
Either way the chunk is returned whole, because the browser decodes one
complete blob per chunk and `speech.ack_floor_seconds` needs a whole
container to read a length out of.

Two things make the format change safe. The audio frame carries no MIME type
(server.py base64s it into a `{"type": "audio"}` message) and the browser's
`decodeAudioData` sniffs the container, so WAV needs no frontend change; and
`speech.wav_seconds` was added alongside `mp3_seconds` so the ack floor still
has a length to work from — without it every local chunk would be a blob with
no floor, which is the older, worse resume behaviour.

The text goes to `say` over STDIN (`-f -`), never as an argument. It is
model-written and arrives through speech recognition, so a chunk beginning
"-r 500 ..." would otherwise be read as flags — the same reasoning
gh_lookup.py applies to `gh`, one step further because here the input is not
even the user's own words.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("jarvis.tts")

FISH_TTS_URL = "https://api.fish.audio/v1/tts"

BACKEND_SAY = "say"
BACKEND_FISH = "fish"
BACKENDS = (BACKEND_SAY, BACKEND_FISH)
DEFAULT_BACKEND = BACKEND_SAY

# Daniel is macOS's en_GB male voice — the closest of the built-ins to a
# British butler, and present on a stock install. System Settings ->
# Accessibility -> Spoken Content offers a free "Daniel (Premium)" download
# that this same name then resolves to, so the setting need not change to get
# the better voice.
DEFAULT_SAY_VOICE = "Daniel"

# 22.05 kHz mono 16-bit: the rate `say` synthesises at, so asking for more
# only inflates the base64 in every audio frame. ~44 KB per spoken second.
SAY_SAMPLE_RATE = 22050


@dataclass
class SynthResult:
    audio: bytes
    first_byte_sec: float
    total_sec: float


def resolve_backend(backend: Optional[str] = None) -> str:
    """The backend to use: the argument, else JARVIS_TTS_BACKEND, else `say`.

    An unrecognised name falls back to the default rather than raising or
    going silent — a typo in `.env` must not cost the user his voice.
    """
    name = (backend or os.getenv("JARVIS_TTS_BACKEND") or DEFAULT_BACKEND).strip().lower()
    if name not in BACKENDS:
        log.warning(f"unknown JARVIS_TTS_BACKEND {name!r}; using {DEFAULT_BACKEND!r}")
        return DEFAULT_BACKEND
    return name


def resolve_voice(voice: Optional[str] = None) -> str:
    return (voice or os.getenv("JARVIS_TTS_VOICE") or DEFAULT_SAY_VOICE).strip()


def resolve_rate(rate: Optional[int] = None) -> int:
    """Words per minute, 0 meaning "the voice's own default"."""
    if rate:
        return int(rate)
    try:
        return int((os.getenv("JARVIS_TTS_RATE") or "0").strip() or 0)
    except ValueError:
        return 0


async def synthesize_chunk(text: str, *, api_key: str = "", voice_id: str = "",
                           client: Optional[httpx.AsyncClient] = None,
                           latency: str = "balanced", timeout: float = 15.0,
                           backend: Optional[str] = None,
                           voice: Optional[str] = None,
                           rate: Optional[int] = None) -> Optional[SynthResult]:
    """Synthesise one chunk, or None if it could not be spoken.

    None is the only failure mode, exactly as before: the scheduler treats a
    chunk it cannot speak as a chunk to fall back on text for, and a raised
    exception here would take the mouth down with it.
    """
    text = (text or "").strip()
    if not text:
        return None
    if resolve_backend(backend) == BACKEND_FISH:
        return await _synthesize_fish(text, api_key=api_key, voice_id=voice_id,
                                      client=client, latency=latency, timeout=timeout)
    return await _synthesize_say(text, voice=resolve_voice(voice),
                                 rate=resolve_rate(rate), timeout=timeout)


async def _synthesize_say(text: str, *, voice: str, rate: int,
                          timeout: float) -> Optional[SynthResult]:
    """macOS `say` into a WAV file, read back whole.

    A file, not a pipe: WAV's header carries the data length, so `say` seeks
    back to write it and `-o -` produces nothing at all. The file lives in a
    per-call temporary directory, so two chunks synthesised at once cannot
    collide, and it is gone before this returns — audio JARVIS speaks is
    never left on disk.
    """
    if shutil.which("say") is None:
        log.error("no `say` on PATH: local TTS needs macOS (or set JARVIS_TTS_BACKEND=fish)")
        return None

    t0 = time.monotonic()
    argv = ["say", "-f", "-", "--file-format=WAVE",
            f"--data-format=LEI16@{SAY_SAMPLE_RATE}"]
    if voice:
        argv += ["-v", voice]
    if rate:
        argv += ["-r", str(rate)]

    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as tmp:
            out = Path(tmp) / "chunk.wav"
            err = await _spawn_say(argv + ["-o", str(out)], text=text, timeout=timeout)
            if err is not None:
                log.error(f"TTS `say` failed for {text[:40]!r}: {err}")
                return None
            try:
                audio = out.read_bytes()
            except OSError as e:
                log.error(f"TTS could not read `say` output: {e}")
                return None
    except OSError as e:                 # the temporary directory itself
        log.error(f"TTS could not make a working directory: {e}")
        return None

    if not audio:
        return None
    total = time.monotonic() - t0
    return SynthResult(audio, total, total)


async def _spawn_say(argv: list[str], *, text: str,
                     timeout: float) -> Optional[str]:
    """Run `say`, feeding it `text` on stdin. None on success, else the reason.

    The single process boundary of this module, so tests mock it once rather
    than patching `asyncio.create_subprocess_exec` per call — the pattern
    `preflight._run_subprocess` and `dialog._osascript` already keep. Never
    raises: a failure here must cost one chunk of speech, not the mouth.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return f"could not spawn `say`: {e}"

    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(text.encode("utf-8")), timeout=timeout)
    except asyncio.TimeoutError:
        # Kill and reap, or the child outlives the utterance and is still
        # talking over the next one (notifier.py's rule for a wedged osascript).
        try:
            proc.kill()
            await proc.communicate()
        except Exception as e:
            log.debug(f"TTS could not reap a timed-out `say`: {e}")
        return f"timed out after {timeout}s"

    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        return f"exit {proc.returncode}: {detail}" if detail else f"exit {proc.returncode}"
    return None


async def _synthesize_fish(text: str, *, api_key: str, voice_id: str,
                           client: Optional[httpx.AsyncClient],
                           latency: str, timeout: float) -> Optional[SynthResult]:
    if not api_key:
        return None
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    t0 = time.monotonic()
    first: Optional[float] = None
    buf = bytearray()
    try:
        async with client.stream(
            "POST", FISH_TTS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"text": text, "reference_id": voice_id, "format": "mp3", "mp3_bitrate": 128, "latency": latency},
            timeout=timeout,
        ) as resp:
            if resp.status_code != 200:
                log.error(f"TTS {resp.status_code} for {text[:40]!r}")
                return None
            async for part in resp.aiter_bytes():
                if first is None:
                    first = time.monotonic() - t0
                buf.extend(part)
    except (httpx.HTTPError, OSError) as e:
        log.error(f"TTS error: {e}")
        return None
    finally:
        if own:
            try:
                await client.aclose()
            except Exception as e:      # never turn a clean None into an exception
                log.debug(f"TTS client close failed: {e}")
    if not buf:
        return None
    return SynthResult(bytes(buf), first if first is not None else 0.0, time.monotonic() - t0)
