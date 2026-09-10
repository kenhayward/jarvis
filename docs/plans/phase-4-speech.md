# Phase 4: server-side speech recognition

The design document [`cross-platform-port.md`](cross-platform-port.md)
referenced but never wrote. It names phases 4b, 4c and 4d in its rules — rule
2 exempts them from "no phase changes macOS behaviour", so they are
load-bearing — and nowhere says what they are. This is that.

Companion documents: [`cross-platform-port.md`](cross-platform-port.md) for
why the phases are ordered as they are, and
[`windows-handoff.md`](windows-handoff.md) for the working record of phase 3.

Written 2026-09-10, immediately after phase 3's code closed. The
measurements quoted below were taken on 2026-09-09.

## What this phase is for

**Unblocking Electron, and nothing else.** Success is that JARVIS hears the
user with no Chrome involved. That is the driver, chosen deliberately over
two alternatives worth naming, because it decides what gets cut when this
slips:

* *Fixing the voice experience on macOS* — the sidecar's other payoff, and
  the reason `cross-platform-port.md` considered swapping phases 3 and 4. Not
  the driver, so echo work is cuttable rather than central.
* *A working Windows voice build* — phase 3 left this unproven, but Chrome-only
  STT already works there, so it is not what this phase is for.

## The premise this whole phase rests on, and it is NOT measured

`cross-platform-port.md` says:

> Chromium's speech service is a Google web service reached with keys only
> Google's own builds carry, so **wrapping the existing page in Electron
> deletes the microphone**.

**Nobody has run that experiment.** It is the same shape as the two premises
that were carried for months in phase 3 and turned out to be wrong when
finally measured — `create_subprocess_exec` cannot run a `.cmd` (it can), and
the launcher's cmd.exe fallback works (it never had). Both were believed,
written into docstrings, and relied upon by code and by tests that passed
without testing them.

Worse, the *refinement* this design depends on is also unmeasured. The
argument below assumes an Electron renderer keeps `getUserMedia` and Web
Audio and loses **only** `webkitSpeechRecognition`. That is very likely true
and it is still a claim, and the entire "endpointing stays in the page"
decision falls if it is wrong.

**So phase 4 opens with a spike, not with code.** See 4-zero below. It is
perhaps an hour's work and it can invalidate the rest of this document, which
is exactly why it goes first.

## What is measured, as of 2026-09-09

Read off the code, not remembered:

* `frontend/src/voice.ts` runs `webkitSpeechRecognition` in the page, which
  does **three** jobs: voice activity detection, endpointing, and
  transcription. Replacing it means replacing all three, and only the third
  is what Electron takes away.
* The page **already holds a `getUserMedia` stream open** for the life of the
  page (`voice.ts:104`) — but only to drive the orb's level meter through an
  `AudioContext`. The microphone is already open; nothing is done with the
  samples.
* `main.ts:84` sends `{type: "transcript", text, isFinal: true}`, and
  `main.ts:88` sends `{type: "interim", text}`. **Text, never audio.**
* `server.py:6810` handles `kind == "transcript" and msg.get("isFinal")`.
* **There is no binary WebSocket path in either direction.** No `send_bytes`,
  no `receive_bytes`, no `binaryType`, anywhere. Audio reaches the page as
  base64 inside a JSON message (`server.py:6738`):
  `{"type": "audio", "utt": 3, "idx": 1, "data": "<base64 mp3>", "text": "..."}`
  and the page decodes it with `atob` (`voice.ts:571`). The WebSocket handler
  reads with `receive_text()` only.

  **`CLAUDE.md` is wrong about this.** It says "Communication: WebSocket (JSON
  messages + binary audio)". Correcting that line belongs to this phase, since
  the phase is where it starts to matter.

## The design

### The seam is the `transcript` message

The server already accepts `{type: "transcript", text, isFinal: true}` from
the browser. With a local backend, **the server raises that same event
itself** once it has transcribed a segment.

Everything downstream is then untouched: the brain, the speech scheduler, and
all 1265 lines of `speech.py` including every echo heuristic. That is what
keeps this from becoming a rewrite, and it is what keeps rule 2 true for
everything that is not the deliverable.

It also means 4a can land with `browser` still the default and change nothing
observable at all — the plumbing is in place and dormant.

### `stt.py`, mirroring `tts.py`

`tts.py` already solved this problem for the mouth and the shape is proven:

* named backends and a default (`BACKEND_SAY`, `resolve_backend()`)
* a readiness map that asks whether each backend can actually run
  (`piper_bin() is not None and piper_model_path() is not None`)
* **a fallback rather than silence** — a configured backend that fails hands
  over to `say`, and JARVIS says so once

`stt.py` gets the same: `BACKEND_BROWSER` (always ready, the default) plus
whatever wins the bake-off, `JARVIS_STT_BACKEND` to choose, and a fallback to
`browser` rather than going deaf. `cross-platform-port.md`'s cut-list already
asked for exactly this — "keep `browser` as the default STT backend and
document Chrome as a requirement for voice".

### Audio travels as base64 in a JSON message

A new client→server frame carrying one utterance, mirroring the existing
audio-down frame rather than introducing the codebase's first binary path.

One utterance at 16 kHz mono 16-bit is roughly 96 KB for three seconds, ~130 KB
base64. The 33% overhead is real and it buys consistency with the only audio
frame that already exists, one protocol shape instead of two, and nothing new
for `web_auth` to reason about. If continuous streaming is ever built, that is
when a binary path earns its place — on a per-frame budget where the overhead
actually matters.

### Endpointing stays in the page

Chrome's endpointer decides where an utterance ends today, and Web Audio can
do the same job in an Electron renderer — **subject to the 4-zero spike**.

`speech.py` records the measured behaviour of the current endpointer, and any
replacement is judged against these, not against a clean-room notion of
correctness:

* it "closes a segment when his voice tails off and hands the user's FIRST
  word over as a final on its own" — measured live 2026-09-04, arriving 1–2s
  after the last chunk was acked, which is why `SHORT_ECHO_GRACE_SEC` is 0.75
  rather than the 6s the longer window uses
* a mis-hear over a speaker returns something *near* JARVIS's words but not
  equal to them — `"Found it — chitauri is idle on ..."` came back as
  `"found it guitar an"` and cut him off with two chunks unplayed

Those comments are the best specification of the current behaviour that
exists. A replacement endpointer that regresses them is a downgrade even if it
is architecturally cleaner.

## Sub-phases

### 4-zero — the spike, before any code

Wrap the existing page in a bare Electron shell and answer, by running it:

1. Does `webkitSpeechRecognition` actually fail there? (The premise.)
2. Does `getUserMedia` still work? (The refinement everything else rests on.)
3. Does Web Audio still work, well enough to do VAD in the renderer?

**If (2) or (3) is false, this document is wrong** and the boundary has to move
to continuous streaming with server-side VAD — a substantially larger phase.
Better to learn that in an hour than in a fortnight.

Output is an answer, not code. Anything built is throwaway and labelled so.

### 4a — the plumbing, with nothing switched on

* `stt.py` with `BACKEND_BROWSER` as the default
* the audio-in frame, page → server
* the server raising `transcript` itself when the backend is not `browser`
* `web_auth` and the settings surface updated to match
* the `CLAUDE.md` binary-audio correction

**Ships with `browser` default, so user-visible behaviour is unchanged.** That
is the point: the risky part lands inert and can be exercised before it is
relied on.

### 4b — the bake-off

Throwaway harness, not shipped code. Records real utterances **through the
real microphone, in the real room**, runs the candidate engines over them, and
reports:

* accuracy on the hard cases above, not on clean read speech
* latency from end-of-utterance to final transcript
* install footprint, measured the way `requirements-piper.txt` measured
  piper's (160 MB of site-packages and a 63 MB model, stated in the file)

Candidates to weigh, against CLAUDE.md's rule that a dependency argues for
itself and that a subprocess is preferred to a package:

| candidate | for | against |
|---|---|---|
| whisper.cpp as a subprocess | mirrors piper exactly; no Python package on the voice path | no clean `pip install`; user must obtain or build a binary |
| faster-whisper (optional pip) | piper's ergonomics — one requirements file | a real package (CTranslate2) on the hot voice path |
| OS-native per platform | no dependency, no model | two implementations, divergent accuracy, and makes STT platform-bound when portable is the default |

**This phase needs the user.** Latency and footprint can be measured alone;
whether an engine hears *this person in this room* cannot.

### 4c — adopt the winner

The winning engine becomes a real backend behind `stt.py`, with its dependency
argued in the commit message. Electron is unblocked at this point.

### 4d — echo cancellation: OUT OF SCOPE, and deliberately

Acoustic echo cancellation needs the server to know exactly which samples it
played and when. **The segment boundary does not provide that**, and that was
the acknowledged cost of choosing it.

So the heuristics in `speech.py` — `_echo_share`, `_is_stem_echo`,
`ECHO_SHARE_WHILE_AUDIBLE`, `SHORT_ECHO_GRACE_SEC`, the four-character stem
rule — all stay exactly as they are. `cross-platform-port.md` already lists
this first on its cut-list and calls them "ugly but tuned"; nothing downstream
depends on removing them.

Revisit only if the driver changes from Electron to voice quality, which would
also change the boundary decision in 4a.

## What would make this design wrong

Stated plainly, so it is falsifiable:

* **4-zero finds `getUserMedia` or Web Audio broken in Electron.** The
  segment boundary collapses; continuous streaming and server-side VAD become
  mandatory, and 4a is a much larger piece of work.
* **A page-side VAD cannot match Chrome's endpointer** on the cases
  `speech.py` documents. Then endpointing has to move server-side even though
  capture does not, which is an awkward middle the current design avoids.
* **The bake-off disappoints on accuracy.** `cross-platform-port.md` already
  has the answer: keep `browser` as the default and document Chrome as a
  requirement for voice. Everything in 4a survives that outcome, which is
  another reason it ships inert.

## Rules carried from phase 3

Not new, but they are the ones this phase will be tempted to break:

* **Measure before writing a comment as fact.** Phase 3 cost real work twice
  by not doing this. 4-zero exists because of it.
* **The macOS suite is the gate**, and it cannot be run from the Windows box.
* **A dependency argues for itself in its commit message**, and a subprocess
  is preferred to a package.
* **Pin the rule, not the string.** Two tests were found in one day that
  passed while asserting nothing.
* PRs to `kenhayward/jarvis` with the base passed explicitly.
