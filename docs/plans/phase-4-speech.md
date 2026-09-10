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

### Audio travels as base64 in a JSON message

One utterance per frame, base64 inside JSON, mirroring the existing audio-down
message rather than introducing the codebase's first binary path.

One utterance at 16 kHz mono 16-bit is roughly 96 KB for three seconds, ~130 KB
base64. The 33% overhead is real and it buys consistency with the only audio
frame that already exists, one protocol shape instead of two, and nothing new
for `web_auth` to reason about. If continuous streaming is ever built, that is
when a binary path earns its place — on a per-frame budget where the overhead
actually matters.

*This decision was reversed and restored on 2026-09-10. See "How the boundary
moved three times in one day".*

### Endpointing stays in the page

4-zero confirmed the page can do this: Web Audio survives Electron on both
platforms, with a median of 13 against a floor of 1.

It is also where the audio already is, and — decisively — where the echo
cancellation already is. The browser applies AEC to the capture before any
consumer sees it, so a page-side endpointer is looking at *cleaned* audio,
which is exactly what an endpointer needs.

*This decision was reversed and restored on 2026-09-10. See "How the boundary
moved three times in one day".*

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
| **4c** | the segment upload frame, and the engine behind it | **DONE** 2026-09-10 |
| **4d** | echo cancellation | **cuttable** — the browser already does it, verified on the product's path |

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

### 4c — the segment upload frame, and the engine behind it — **DONE 2026-09-10**

**The engine: `faster-whisper`, `base.en`, with a project-name prompt.**
whisper.cpp WAS tested rather than assumed away — b4938, same weights, same
twenty recordings, identical scores (0.00/0.15/0.00, 4/5 tool words), half the
disk, nothing on the Python path. It lost on one measured fact: its CLI
reloads the 141 MB model every call, 0.59s fixed against 0.03s per second of
audio, so a 0.41s response becomes 0.75s permanently. JARVIS is a long-lived
server and pays that once. The argument, including the `whisper-server.exe`
route not taken, is in `requirements-stt.txt`.

**The prompt IS the model choice.** `base.en` alone got 4/5 tool-argument
words; with the user's project names as `initial_prompt`, 5/5 at 0.40s —
matching `small.en` at 2.5x the speed and a third of the disk. Drop the prompt
and this should become `small.en`.

**The page still does the hearing, and that is the whole shape of it.** Echo
cancellation exists only in the page, where the audio is also played; ship the
raw microphone and it is thrown away. So endpointing lives with the audio and
the cancellation, transcription lives where the model is, and the seam between
them is one utterance of WAV.

`_final_transcript` was extracted from the WebSocket handler so the replay
check, the echo verdict and the fresh-start check have exactly one
implementation. There are two ways a sentence now reaches JARVIS and only one
of them is in use on a default install — precisely the arrangement where a
second copy would rot unnoticed. A test holds `speech.user_final` to that one
caller.


* the **audio-in frame**, page -> server, one utterance as base64 in a JSON
  message. Deferred out of 4a for having no caller; 4c is the caller.
* **page-side endpointing** via Web Audio, judged against Chrome's endpointer
  on the cases `speech.py` records — not against a clean-room notion of
  correct. It works on audio the browser has already echo-cancelled.
* the **server raising `transcript` itself** when the backend is not `browser`
* the winning **engine** as a real backend behind `stt.py`, its dependency
  argued in the commit message

Electron is unblocked at the end of this.

**Choose the engine against this shape, not against 4b's table.** 4b measured
whole utterances on raw audio; the real input is one echo-cancelled utterance
at a time, which is closer, but the candidates should be re-scored on the
recordings in `.agents/stt-bakeoff-2026-09-10/` once captured the product's
way. `base.en` at 0.41s versus `small.en` at 1.01s is a real choice and 4b's
own numbers say the smaller model is better at short words while the larger
one is better at project names.

**Still unanswered: whisper.cpp.** CLAUDE.md prefers a subprocess to a
package, and the subprocess candidate was never tested because it means
downloading and running an executable from a GitHub release. `faster-whisper`
is currently winning by default rather than on merit, and that should be
settled before it is adopted rather than after.

### 4d — echo cancellation: CUTTABLE, and it took three attempts to be sure

**The browser already does this, it is already switched on, and it already
works.** Measured 2026-09-10 on the product's own capture path.

`frontend/src/voice.ts:104` requests `getUserMedia({ audio: true })`, and that
grants — verified, not assumed, Chrome 152:

    echoCancellation = true
    noiseSuppression = true
    autoGainControl  = true

Capturing through that path while JARVIS spoke, and transcribing the result:

    AEC on   rms 412   "It's me talking over here."          <- the user, no JARVIS
    AEC off  rms 677   "Found it. This is me talking a title
                        on the staging branch."               <- JARVIS bleeding in

Both models agreed. AEC removed roughly 40% of the captured energy — the
far-end signal — and with it, JARVIS.

**It sits upstream of every design choice below**, so the server never needs
its own AEC and never needs the reference signal. That is true whether audio
leaves the page as segments or as a stream, which is why this no longer
constrains the boundary at all.

So the heuristics in `speech.py` stay as they are — and their existence is
now better understood rather than merely tolerated. They run on audio that
has ALREADY been echo-cancelled, which means they were always handling AEC's
RESIDUE, not raw echo. That is a much more modest job than it looked, and it
explains why they are a pile of tuned thresholds rather than a signal
processing stage.

**What is NOT established.** The AEC test used a longer interruption than 4b's
`"stop"` and `"cancel that"`. Short interruptions are the harder case — less
for the recogniser to hold on to, more chance the residue dominates — and that
case has not been measured through the browser path. If barge-in ever feels
unreliable in practice, that is the experiment to run, and 4b's recordings in
`.agents/stt-bakeoff-2026-09-10/` are the reference to run it against.

## How the boundary moved three times in one day

Kept in full, because the mistake is more instructive than the answer and
tidying it away would leave the next reader unable to see why the rule at the
end of this section exists.

**1. Segments (morning).** Electron keeps `getUserMedia` and Web Audio and
loses only the Google speech service, so capture and endpointing can stay in
the page and only transcription needs to move. Sound reasoning, and it is
where this document ended up.

**2. Streaming (afternoon).** 4b recorded twenty utterances and found every
engine transcribing JARVIS rather than the user in all four barge-in takes.
Barge-in appeared to be lost, so echo cancellation was promoted from cuttable
to required — and AEC needs the reference signal, which segments cannot
provide. The boundary moved to continuous streaming and phase 4 roughly
doubled.

**3. Segments again (evening).** 4b's harness captured with `sounddevice` — a
RAW MICROPHONE TAP. The product captures through `getUserMedia`, which applies
AEC before any consumer sees a sample. **The measurement was of a path this
product never uses.** Re-run through the browser, the same scenario transcribes
the user and not JARVIS.

**The rule that comes out of it, and it is not "measure more".**

The whole port has been repeating "measure, do not assume", and 4b DID measure
— carefully, with guards for muted output and clipping, in a real room with a
real microphone. It still produced a conclusion that reversed a design
decision and was wrong.

**A measurement must go through the product's own path, or it measures
something else.** `sounddevice` was the convenient way to reach the
microphone; `getUserMedia` was the correct one, because it is what JARVIS
uses. The convenient tool and the correct tool were different, and nothing in
the result could reveal it — the recordings were real, the levels were good,
the guards all passed, and the numbers were wrong.

Ask of any harness: *does the signal reach it the way it reaches
production?* If not, it is measuring a neighbour of the thing you care about.

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
