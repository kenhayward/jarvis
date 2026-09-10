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

## The premise this phase rests on — MEASURED 2026-09-10, and it holds

`cross-platform-port.md` says:

> Chromium's speech service is a Google web service reached with keys only
> Google's own builds carry, so **wrapping the existing page in Electron
> deletes the microphone**.

That had never been run. It was the same shape as the two beliefs phase 3
carried for months and found wrong the day they were tested, so this document
originally opened by refusing to build on it. **4-zero has now been run** — a
throwaway Electron shell, Electron 44.3.0 / Chrome 152.0.7977.78, on Windows —
and the premise is **TRUE**. The design below stands.

**But it is true in a way a feature check would miss, and that is the finding.**

    defined?          YES
    start() result:   ERROR event: error=network

`webkitSpeechRecognition` **is defined** in an Electron renderer. The
constructor works. `start()` succeeds and `onstart` fires. It then fails at
RUNTIME with `error=network`, because the Google API keys are not there.

So `if (!window.webkitSpeechRecognition)` — the obvious capability check, and
the one `voice.ts:152` already does to pick its constructor — reports that
everything is fine inside Electron. Anything deciding whether to use the
browser backend must treat a `network` error at runtime as the signal, never
the presence of the API. Getting that wrong ships an Electron build whose
microphone appears to work and silently never returns a transcript.

The refinement the whole design leans on is confirmed too:

    getUserMedia:  OK - track "Default - Microphone (Yeti Nano)" state=live
    Web Audio:     floor=0/127  median=13/127  peak=61/127  (8s, 80 frames)

Both survive. Web Audio sees real signal with 61 levels between quiet and
loud, which is a threshold a VAD can work with — measured with speech played
into the room rather than against a silent mic, because a single peak from a
quiet room proves the API returns buffers and nothing more.

**Three traps found while measuring, worth more than the result.**

*(a) The permission handler.* Electron denies media requests unless the app
installs a `session.setPermissionRequestHandler`. Without it `getUserMedia`
fails, and a spike that had not granted it would have "proved" the opposite
conclusion and sent this phase down the streaming road for no reason. The
spike logs the grant for exactly that reason.

*(b) A quiet reading is not evidence — and it has a second door.* Sampling a
silent room gives a peak near zero, which only proves the API returns
buffers. So the Windows run played speech and reported a spread. **The macOS
run found the hole in that.** Its first attempt reported `median=1/127` with
`say` running, the mic live and every API returning buffers — because the
system OUTPUT WAS MUTED. Nothing in the result could reveal it: 1/127 is
exactly what a genuinely quiet room gives. It was caught only by checking the
audio routing after the number looked wrong.

The macOS harness now reads the speaker state, forces it, restores it, logs
it either way, and refuses a Q3 result whose speech window cannot be
separated from its own quiet baseline. **The Windows run had no such guard
and got the right answer by luck** — the machine simply happened not to be
muted. Anyone repeating this should use the macOS harness's shape, not the
Windows one.

*(c) The scale is 0..128, not 0..127, and clipping hides at the top.*
`Math.abs(byte - 128)` yields 128 for byte 0, so the Windows probe's "/127"
label was wrong and its first macOS counterpart printed `peak=128/127`. Worse,
a saturated microphone reads as a healthy peak: at output volume 100 the
built-in mic clipped (`peak=127`, 2 clipped samples) and the run had to be
repeated at 55 to get the unclipped 74 quoted above. Count clipped samples
separately or a clipped signal will be read as a strong one.

**macOS: MEASURED TOO, same day, same Electron build.** Like-for-like, and
the premise holds on both:

| | Windows | macOS |
|---|---|---|
| Q1 defined? | YES | YES |
| Q1 `start()` | `error=network` | `error=network` |
| Q2 `getUserMedia` | OK (Yeti Nano) | OK (built-in, 48 kHz, 1 ch) |
| Q3 floor / median / peak | 0 / 13 / 61 | 1 / 13 / 74 |

The macOS run also captured the full event sequence — `start` →
`audiostart` → `error:network` → `end` — with speech playing aloud
throughout, so the failure is not "nothing was said". Both
`webkitSpeechRecognition` and `SpeechRecognition` are defined there. **The
median is identical at 13 on both platforms**, against a quiet baseline whose
median is 1.

So: Electron deletes transcription and leaves the microphone and Web Audio
intact, on both platforms. The segment boundary stands.

### A THIRD gate, on macOS only — and phase 5 needs this

`setPermissionRequestHandler` is **necessary but not sufficient** on macOS.
There is a second gate Windows does not have: TCC. On the first run the
status went `not-determined` → `granted` via
`systemPreferences.askForMediaAccess('microphone')`.

**A packaged macOS Electron app needs `NSMicrophoneUsageDescription` in its
`Info.plist` AND must call `askForMediaAccess`**, or `getUserMedia` fails —
and it fails in a way that looks *exactly* like the permission-handler trap
below but is not. You would install the handler, still fail, and have no way
to tell which gate was shut. That belongs in phase 5's notes as much as here.

(Chromium routed both a permission *request* and a permission *check* for
media; both were granted, so which is load-bearing is not yet known.)

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

### ~~Audio travels as base64 in a JSON message~~ — SUPERSEDED 2026-09-10

This argued for one utterance per frame, base64 inside JSON, mirroring the
existing audio-down message, and explicitly said: *"If continuous streaming is
ever built, that is when a binary path earns its place — on a per-frame budget
where the overhead actually matters."*

**4b forced continuous streaming (see 4d), so that condition is met and the
conclusion flips.** A binary WebSocket path now earns its place. It will be
the codebase's first in either direction, and `web_auth` gains a second frame
shape to reason about — a real cost that was correctly weighed and is now
worth paying, rather than one that was overlooked.

### ~~Endpointing stays in the page~~ — SUPERSEDED 2026-09-10

4-zero confirmed the page CAN do this: Web Audio survives Electron on both
platforms, with a median of 13 against a floor of 1. The decision was sound on
the evidence available.

**4b changed the evidence.** Acoustic echo cancellation needs the reference
signal — the samples the server actually played — and it has to be applied
BEFORE endpointing, or the endpointer segments on JARVIS's voice. So VAD and
endpointing move server-side with the audio.

The measured behaviour of the endpointer being replaced is below, and it is
the bar, not a starting point.

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

| | | state |
|---|---|---|
| **4-zero** | the spike, before any code | **DONE** 2026-09-10, both platforms |
| **4a** | `stt.py`, settings reporting, the `voice.ts` message fix | **DONE** — `browser` still default, nothing user-visible changed |
| **4b** | the bake-off, real mic and real room | **DONE** — SAPI eliminated; **overturned the boundary** |
| **4c** | streaming audio, server-side VAD and endpointing | next, and larger than it was |
| **4d** | echo cancellation | **REQUIRED**, promoted by 4b |

### 4-zero — the spike — **DONE 2026-09-10 on Windows**

| question | answer |
|---|---|
| Does `webkitSpeechRecognition` fail there? | **Yes** — but it is DEFINED and fails at runtime with `error=network`, not absent |
| Does `getUserMedia` still work? | **Yes** — real track, `state=live`, given a permission handler |
| Does Web Audio work well enough for VAD? | **Yes** — median 13 against a quiet baseline of 1, both platforms |

All three as the design needed, **on Windows and macOS**. Nothing is
invalidated; 4a may proceed.

Carried forward to phase 5: macOS has a second, TCC gate that
`setPermissionRequestHandler` does not satisfy — see above. That is the one
finding here that is not about phase 4 at all.

The spike itself was throwaway and is not in the repository.

### 4a — the plumbing, with nothing switched on

**Scope corrected while implementing, 2026-09-10.** Two items originally
listed here were building ahead of a caller, which is the thing this
repository refuses to do everywhere else, so both moved to 4c:

* ~~the audio-in frame, page → server~~ — **deferred.** `BACKENDS` is
  `("browser",)`; there is no engine to transcribe anything until 4c, so a
  receive path would take audio and discard it. The screen-capture work
  settled this precedent already: "a half-built eye is worse than a closed
  one". The frame lands in the commit that can use it.
* ~~a Python `browser_is_usable` / `explain_browser_error`~~ — **deferred.**
  They had no caller: the server's `mic` frame is logged and drives nothing
  by deliberate design, and giving it teeth is a behaviour change 4a promised
  not to make. The KNOWLEDGE they encoded belongs in `voice.ts`, where the
  recogniser is and where the decision is actually made, and that is where it
  went.

What 4a actually is:

* `stt.py` — `BACKEND_BROWSER`, `resolve_backend`, `backends_ready`, with the
  same typo-falls-back rail `tts.py` has
* `/api/settings/status` reporting `stt_backend` and `stt_backends_ready`,
  which is `stt.py`'s caller, so the module is not itself speculative
* `voice.ts` telling the truth about a `network` error — see below
* the `CLAUDE.md` binary-audio correction

**Ships with `browser` default, so user-visible behaviour is unchanged**
except for one message that was actively misleading.

#### The one behaviour change, and why it is not scope creep

`voice.ts` said, on any `network` error:

    "Speech recognition lost its connection — that sentence was dropped."

4-zero measured that in Electron this error fires every time, for ever,
because there is no speech service behind the recogniser at all. That wording
sends the user to check their wifi for a fault no wifi will fix, while the
engine retries silently.

It now turns on `everHeard` — whether a transcript has EVER come back on this
page — because that is the only positive evidence the service is reachable.
Never heard anything: say there is no speech service. Heard something before:
the old message is right, and it stays. Deliberately NOT a feature check, for
the reason the whole spike exists.

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

#### DONE 2026-09-10. What was run, and what it found

Twenty utterances through a Yeti Nano in a real room — five ordinary
commands, five carrying project names, six single words, and four spoken over
JARVIS's own piper voice out of a separate speaker, so the echo path is
speakers -> room -> mic rather than a loopback.

**The headline is in 4d: every engine transcribed JARVIS rather than the user
in every echo take, and that overturned the design.** The rest is the engine
comparison it was run for.

    condition   base.en   small.en   SAPI
    control        0.00       0.00   0.32
    domain         0.15       0.10   0.48
    short          0.00       0.17   0.33

    key words      4/5        5/5     1/5     (the ones that reach a tool)
    latency       0.41s      1.01s   0.28s    (median, transcription only)
    model load     4.1s       8.0s      -

**Windows SAPI is out.** Free, built in, no download, fastest — and it heard
"voice backend" as "Boris Becker" and "show me the last run" as "and nor does
fortune in the last run". 1 of 5 tool arguments survived. That is not a trade
at any price, and it is worth having measured rather than assumed: this port
has been wrong about "obvious" often enough.

**Between the two whisper models there is a genuine split**, and it is not
"bigger is better":

* `small.en` is the only engine that got **every** tool-argument word,
  including `chitauri`. Those matter out of proportion: a mangled project name
  is a failed action.
* `base.en` was **perfect on all six single words** where `small.en` heard
  "now" as "No" — and single words are what the endpointer hands over alone.
* `base.en` is 2.4x faster (0.41s vs 1.01s per utterance).

Not resolved here, because the boundary change in 4d moves the goalposts: with
continuous streaming the latency budget is per-frame rather than per-utterance,
and the comparison should be re-run against that. Recorded so the re-run starts
from evidence.

**What this bake-off did NOT test.** `whisper.cpp` as a subprocess — the
candidate that best matches CLAUDE.md's "prefer a subprocess to a package" —
was left out because it means downloading and running an executable from a
GitHub release, which was not agreed. **So the subprocess-versus-package
question is still open**, and a package (`faster-whisper`, 160 MB of
site-packages measured as the marginal cost on top of piper) is currently
winning by default rather than on merit.

**And the numbers are optimistic.** These are prompted phrases, which is read
speech, which is easier than spontaneous speech. The prompts bought a known
reference and therefore a real word error rate rather than somebody preferring
one transcript to another. Read speech flatters every candidate equally, so
the RANKING holds; the absolute figures do not.

### 4c — the streaming audio path, and the engine behind it

**Rewritten 2026-09-10.** This used to read "adopt the winner", which assumed
the audio was already arriving. After 4d it is the larger half of the phase:

* a **binary** WebSocket frame, page -> server, carrying audio continuously —
  the codebase's first in either direction, and now justified on a per-frame
  budget (see the superseded section above)
* **server-side VAD and endpointing**, judged against Chrome's endpointer on
  the cases `speech.py` records, not against a clean-room notion of correct
* **AEC before endpointing**, or the endpointer segments on JARVIS's voice —
  which is the whole finding of 4b
* the winning engine as a real backend behind `stt.py`, its dependency argued
  in the commit message

Electron is unblocked at the end of this, not the start.

**Re-run the engine comparison against the streaming shape before choosing.**
4b measured whole utterances; streaming has a per-frame budget, and `base.en`
being 2.4x faster than `small.en` may matter more, or less, than it did. The
4b numbers are a starting point and not a verdict.

### 4d — echo cancellation: REQUIRED. Promoted 2026-09-10 by measurement.

**This section used to say "out of scope, and deliberately". 4b proved that
wrong, and the reversal is the most important thing in this document.**

Twenty utterances were recorded through a real microphone in a real room, four
of them spoken over JARVIS's own voice through the speakers. Every engine
tested — `faster-whisper base.en`, `faster-whisper small.en`, and Windows SAPI
— transcribed **JARVIS instead of the user, in all four takes. Twelve out of
twelve.**

    take   WER vs the user's words   WER vs JARVIS's words
    17            3.00                      0.47
    18           10.00                      0.41
    19            2.75                      0.41
    20            6.00                      0.20

The user's interruption did not come back mangled. **It did not come back at
all.**

**It is not a volume artefact, and that was checked rather than assumed.** The
user's voice alone peaks 2473-3281. JARVIS's level in takes 18, 19 and 20 was
2399, 2088 and 1560 — at or BELOW the user's own voice — and the engines still
transcribed him. Only take 17 (8218) was genuinely loud. The mechanism is not
loudness, it is duration and continuity: these models settle on the longest
fluent speaker, and in a real barge-in that is always JARVIS. The user's
interruption is two words; his sentence is twenty.

**What that costs, precisely.** Today Chrome returns the user's words MIXED
with echo, which is exactly why `speech.py` has `ECHO_SHARE_WHILE_AUDIBLE`,
`SHORT_ECHO_GRACE_SEC` and the stem rule — the user's words do arrive, dirty.
With segment-based local STT they stop existing as text. What arrives instead
is a clean transcript of JARVIS's own sentence, presented as though the user
had said it. The existing heuristics would very likely catch that — the
overlap with what he just said is total — so the rail holds and nothing
dangerous reaches the brain. But **barge-in stops working**, and that is a
capability the product has today.

So echo cancellation is not polish. It is what makes interruption possible at
all once transcription moves off the browser, and AEC needs the server to know
exactly which samples it played and when.

**Therefore the boundary moves: segments -> continuous streaming**, with
server-side VAD and endpointing, which is the option this document weighed and
rejected this morning. Consequences, stated so the reversal is not silently
absorbed:

* the audio frame becomes a per-frame budget, so **a binary WebSocket path now
  earns its place** — the base64-in-JSON argument was explicitly conditional on
  one utterance at a time, and that condition is gone
* the page becomes a microphone and a speaker; VAD and endpointing move server
  side and must be judged against Chrome's tuned endpointer, whose measured
  behaviour is recorded above
* `speech.py`'s echo heuristics can eventually be RETIRED rather than
  preserved, which was 4d's original promise and is now back on the table
* phase 4 is substantially larger than it was this morning

**4a survives untouched**, and one decision in it looks much better in
hindsight: the audio-in frame was deferred out of 4a for having no caller.
Had it shipped, it would have shipped the wrong shape. `stt.py`, the settings
reporting and the `voice.ts` message fix are all boundary-agnostic.

**A lesson about falsifiability lists.** This document ends with "What would
make this design wrong" and names three things. **None of them is what
happened.** The list was honest and it was incomplete, because it could only
contain failures that had been imagined. What actually overturned the design
was a measurement nobody had thought to take — which is the same shape as
every other correction in this port, and an argument for running the cheap
experiment even when the design looks settled.

## What would make this design wrong

Stated plainly, so it is falsifiable:

* ~~**4-zero finds `getUserMedia` or Web Audio broken in Electron.**~~
  **Ruled out on BOTH platforms, 2026-09-10.** Both work; the medians are
  identical. This one is closed.
* ~~**A page-side VAD cannot match Chrome's endpointer.**~~ **Moot from
  2026-09-10.** Endpointing moved server-side anyway, for a different reason
  (4d). The bar it must clear is unchanged and is stated above.
* **The bake-off disappoints on accuracy.** Partly answered: on clean speech
  it does not — `small.en` scored 0.00 on ordinary commands and got every
  tool-argument word. `cross-platform-port.md`'s fallback answer (keep
  `browser` as the default, document Chrome as a requirement for voice) is
  still the right one if the streaming rebuild disappoints, and everything in
  4a survives that outcome.

**And the honest entry: none of the three above is what happened.**

The design was overturned on 2026-09-10 by something not on this list — every
engine transcribing JARVIS instead of the user under barge-in. The list was
written in good faith and it was incomplete, because a falsifiability list can
only contain failures somebody already imagined. What broke this design was a
measurement nobody had thought to take.

That is the same shape as every other correction in this port: the
`create_subprocess_exec` belief, the launcher's fallback, the muted speaker on
the macOS spike, the 16 tests skipping in silence. **The lesson is not "write
a better list." It is to run the cheap experiment even when the design looks
settled** — and to distrust a list of risks in proportion to how comfortable
it feels.

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
