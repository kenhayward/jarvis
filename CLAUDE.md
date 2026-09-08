# JARVIS — Voice AI Assistant

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Overview
JARVIS (Just A Rather Very Intelligent System) is a voice-first AI assistant for macOS. It runs locally on your machine, driving Claude Code for development tasks — every execution recorded as a *run* and watchable at `/dashboard`.

## Quick Start
Read `skills/jarvis-setup/SKILL.md` first — it carries setup and debugging
facts (mic-in-Chrome-only, the per-port permission trap, subscription vs. API
key, what an expired login sounds like, Accessibility) that were only learned
by hitting them live, and this walkthrough assumes them.

When a user clones this repo and starts Claude Code, help them:
1. Copy .env.example to .env
2. Install Claude Code (`npm install -g @anthropic-ai/claude-code`, 2.1.224 or
   newer) and log in with `claude` — JARVIS's brain runs on your Claude
   subscription, not on an API key
3. Nothing to sign up for: the voice is macOS's own `say`, offline and
   keyless. For the better local voice: `pip install -r requirements-piper.txt`
   then `python -m piper.download_voices --download-dir data/voices
   en_GB-alan-medium`, and set `JARVIS_TTS_BACKEND=piper` (or pick it in
   Settings). A Fish Audio key is optional and read only with
   `JARVIS_TTS_BACKEND=fish`
4. Install Python dependencies: pip install -r requirements.txt
5. Install the Playwright browser: python -m playwright install chromium
   (`read_page` / `look_at_page` need it)
6. Install frontend dependencies: cd frontend && npm install
7. Generate the SSL certs — see below, they are NOT optional:
   `openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'`
8. Run the backend: python server.py --host 127.0.0.1
9. Run the frontend: cd frontend && npm run dev
10. Open Chrome (mic only works in Chrome) to http://localhost:5173
11. Click to enable audio, speak to JARVIS

**The certs are required for the dev-server workflow**, despite `server.py`
treating them as optional. `server.py` serves HTTPS only when `cert.pem` and
`key.pem` are both beside it, but `frontend/vite.config.ts` hard-codes its
proxy target as `https://localhost:8340`. Measured with a stand-in backend on
8340 and `npx vite`: with a plain-HTTP backend the Vite dev server itself
answers 200 while every proxied `/api` request returns **500**; with an HTTPS
backend the same request returns 200. The page loads either way, which is why
this presents as "the UI is up but nothing works" rather than as an error.

## Architecture
- **Backend**: FastAPI + Python (server.py, ~7000 lines)
- **Frontend**: Vite + TypeScript + Three.js (audio-reactive orb)
- **Communication**: WebSocket (JSON messages + binary audio)
- **AI**: a long-lived Claude Code process (`brain.py`, Sonnet by default) on
  the user's subscription; no Anthropic API calls on the voice path
- **TTS**: `tts.py` — three backends, one call per sentence chunk: macOS
  `say` (WAV, offline, default), `piper` (WAV, offline, neural, optional
  dependency), or Fish Audio (MP3, hosted). `JARVIS_TTS_BACKEND` chooses, and
  whichever is chosen falls back to `say` rather than going quiet — JARVIS
  says so out loud, once, and `/api/settings/status` reports it as
  `tts_fallback_from`
- **System**: AppleScript for Terminal and Chrome integration
- **Runs**: every Claude Code execution goes through one recorded pipeline —
  `run_store.py` (SQLite) + `run_executor.py`, surfaced at `/api/runs`,
  `/ws/runs`, and the `/dashboard` UI
- **Internal tool channel**: the brain reaches JARVIS's tools (session
  listing, steering, etc.) via a stdio MCP child that forwards
  `tools/call` to `POST /internal/tool` over loopback HTTP, bearing the
  token from `data_paths.ensure_tool_token()`.
- **The web boundary** (`web_auth.py`): one ASGI gate above the router.
  Every WebSocket handshake and every state-changing request must carry
  either an `Origin` JARVIS serves from (localhost/127.0.0.1/[::1] on the
  API port or Vite's) or that same tool token. The browser needs no setup —
  it is same-origin through Vite's proxy, so it sends the `Origin` itself.
  There is no CORS: same-origin needs none, and sending none is what stops
  a hostile page reading the GETs that cannot be gated (a same-origin GET
  carries no `Origin` to check). The `Host` header IS checked on every
  request including reads, because DNS rebinding is the way around "no
  CORS". `--host` defaults to `127.0.0.1`; `0.0.0.0` still works and warns,
  and then needs `JARVIS_ALLOWED_ORIGINS`.

## The Run Pipeline
Nothing spawns Claude Code outside `RunExecutor`. Two invariants govern it:

1. **A run always reaches a terminal state.** `succeeded`, `failed`,
   `timed_out`, or `cancelled` — never left stuck in `running` or `queued`.
   Every exit path out of `_drive` writes a terminal status, and callers that
   create a run then hand it off must fail it if they throw before the
   executor takes ownership.
2. **Every state transition is a DB write BEFORE it is a notification.** The
   WebSocket is a cache-invalidation hint, never a source of truth; clients
   reconcile against `/api/runs`.

One more rule for this area: the dashboard never uses `innerHTML` /
`insertAdjacentHTML` — it renders arbitrary LLM and file content, so
everything goes through `createElement` / `textContent`.

A dependency is allowed when it earns its place (`piper-tts` is the first),
but it is still a cost: prefer the standard library and a subprocess to a
package, keep it out of the hot voice path unless it is the point, and say in
the commit why the alternative was worse.

## Key Files
- `server.py` — Main server, WebSocket handler, HTTP API, action system
- `brain.py` — The voice brain: one long-lived `claude -p` process on the
  user's Claude subscription, fed over stdin as stream-json
- `jarvis_mcp.py` — Stdio MCP server exposing JARVIS's tools to the brain;
  forwards `tools/call` to `POST /internal/tool`
- `speech.py` — Sentence splitting and the scheduler that owns every
  utterance JARVIS speaks
- `tts.py` — Synthesis, one call per sentence chunk, three backends behind
  one function. Both local ones write a WAV to a temp file (neither can
  stream: `say -o -` yields nothing, WAV headers needing seek) with the text
  on STDIN, never argv; Fish streams MP3. Measured per sentence on this Mac:
  `say` 0.45s, piper 0.67s warm. A configured backend that fails hands over
  to `say` and the result names the backend that really spoke, so `None` now
  means macOS itself would not speak either — never an exception, the mouth
  survives both
- `frontend/src/orb.ts` — Three.js particle orb visualization
- `frontend/src/voice.ts` — Web Speech API + audio playback
- `frontend/src/main.ts` — Frontend state machine
- `frontend/src/dashboard/` — The `/dashboard` run monitor (vanilla TS)
- `run_store.py` — SQLite `runs` / `run_events` tables, six-value status enum
- `run_executor.py` — Spawns `claude -p --output-format stream-json` and drives
  each run to a terminal state, streaming its events into the store
- `stream_parser.py` — Pure parsing of the stream-json output (no I/O)
- `builds.py` — The spec/brief/plan pipeline behind real, phased,
  multi-session builds (see "The Run Pipeline" above)
- `specs.py` — The review surface: reads back what JARVIS proposed and what a
  build produced
- `projects_view.py` — The Projects tab: a read-only JOIN over runs,
  sessions, plans and the repo, by project
- `session_watch.py` — Watches every Claude Code session on the machine
  (process / conversation / project)
- `session_steer.py` — Sends a message into a running session's inbox socket
- `jarvis_platform/macos/dialogs.py` — Answers a permission prompt in a
  Terminal window by sending it a keystroke (needs Accessibility). The
  closed key vocabulary (`normalize_key`) and the outcome constants are in
  `jarvis_platform/base.py`, not here: they are the protocol, and a second
  implementation does not get to widen either. Was `dialog.py`
- `jarvis_platform/macos/notifications.py` — macOS notification fallback
  when no browser tab is connected to speak through. Reached as
  `jarvis_platform.current().notifications`; a platform without one
  declines rather than raising, because the announcement path must never
  break. Was `notifier.py`
- `jarvis_memory.py` — Long-term memory: a folder of plain Markdown files the
  user can read and edit directly, not a database
- `usage_store.py` — Tracks the subscription's five-hour / seven-day
  rate-limit usage (there is no spend to report — see brain.py)
- `preflight.py` — First-run environment checks: `claude` CLI/login,
  Accessibility, the voice (backend-aware: the `say` binary and whether the
  configured voice is actually installed, or the Fish key), cross-session
  steering
- `claude_env.py` — The environment every spawned Claude Code child gets,
  including the `ANTHROPIC_*` scrub, and `split_command` for the configured
  `claude` path (POSIX splitting destroys a Windows one)
- `jarvis_platform/` — What this machine can do, stated once. `base.py` holds
  the capability constants and `TOOL_CAPABILITIES` (tool name -> capability);
  `macos/` declares all of them, so on a Mac this layer is invisible, and
  holds the implementations as MODULES (not class instances) so the test
  suite can keep patching them across an `importlib.reload(server)`.
  Four consumers read it and they must not disagree: the `/internal/tool`
  dispatch gate, `brain.granted_tools`, the `JARVIS_DISABLED_TOOLS` env block
  in `_write_mcp_config`, and `preflight`'s `_CHECK_CAPABILITIES`. **Not**
  named `platform/` — that would shadow the stdlib module for the whole
  process, since `server.py` runs from the repository root
- `jarvis_platform/macos/launcher.py` — Terminal, browser and editor via
  AppleScript. Reached as `jarvis_platform.current().launcher`. It composes
  its own `cd` and does its own quoting: `shlex.quote` is POSIX, so leaving
  it at the call site meant three copies in `server.py` that would each have
  to be found and corrected for cmd.exe. Was `actions.py`
- `browser.py` — Playwright. Only the headless half is live (`read_page`,
  `capture_page`, behind `read_page` / `look_at_page`); the headful
  `JarvisBrowser` search/research class is reachable from nothing but
  `tests/test_browser_integration.py`
- `screen.py` — Seeing the Mac itself: the window list (`osascript`) and one
  downscaled `screencapture` the brain sees as an MCP image block. Captured
  only on a turn the user drove, never persisted, never on a timer
- `repo_read.py` — Cheap, model-free reading of a repository (no `claude`
  subprocess)
- `project_maker.py` — Creates a new project directory from a spoken name,
  path-validated against the projects root
- `work_mode.py` — Vestigial. `is_casual_question` is imported by `server.py`
  and called by nothing; the Haiku-vs-`claude -p` routing it classified for is
  gone. Left in place only because a test pins it
- `gh_lookup.py` — Repository questions go to `gh`, not to a web search
  (measured: 0.5s vs 9-16s through a `claude -p` turn). It takes what a person
  *says* ("my Arc Loop repo"), never picks between several matches, and every
  `gh` call is an argument list with a deadline — no shell
- `usage_scan.py` — Per-*session* token usage, parsed off Claude Code's own
  `~/.claude*/projects/**.jsonl` transcripts (`usage_store.py` answers the
  different question of subscription-window headroom). Dedupes by
  `(st_dev, st_ino)` because the config roots are hardlinked, and rescans
  incrementally because the corpus runs to hundreds of MB.
  Both it and `session_watch.py` read every config root
  (`~/.claude`, `~/.claude-orcha`, plus `JARVIS_CLAUDE_CONFIG_DIRS`) through
  `session_watch.config_roots`
- `data_paths.py` — Single source of truth for where data is written

## Other directories
- `jarvis_home/` — The brain's own home, templated into the data dir by
  `data_paths.py`: `CLAUDE.md` is JARVIS's system prompt (how he speaks; it
  `@`-imports the memory index), and `connections.json` is the *only* file
  read for MCP servers, because the brain runs with `--strict-mcp-config`.
  `data_paths.py` pins a hash of each — change either and update the hash list
- `skills/jarvis-setup/SKILL.md` — Setup and debugging facts learned live
  (mic-in-Chrome-only, the per-port permission trap, expired logins,
  Accessibility). Read it before answering a setup question
- `migrations/` — One-off SQLite backfills, imported by name from
  `server.py` at startup (`001_dispatches_to_runs.py`); idempotent
- `scripts/` — Generates the README's GIFs (`make_orb_loop.py`,
  `make_dashboard_walkthrough.py`), not part of the running system

## Where the author's own notes live
This repository ships nothing personal. Research notes, milestone
verification checklists and this project's own superpowers specs and plans
were moved to `.agents/`, which is ignored in full — do not re-add them, and
do not treat `git log` as their backup.

Note that `docs/superpowers/specs` and `docs/superpowers/plans` are still a
live convention: `builds.py` and `specs.py` create them **inside the projects
JARVIS builds**. It is only this repository's own copies that are gone.

## Environment Variables
- `ANTHROPIC_API_KEY` — **read by nothing.** Not asked for in setup, not read
  by any module, and the `anthropic` SDK is not a dependency: JARVIS's brain
  and every spawned run go through your Claude Code subscription login.
  `claude_env.child_env()` scrubs every `ANTHROPIC_*` variable from every
  spawned Claude Code child (brain and run pipeline alike) so the CLI can
  never bill an API key instead, and `preflight.py`'s `anthropic_key_leftover`
  check warns you if one is sitting in your `.env` — that is the only place
  the name appears in live code.
- `JARVIS_BRAIN_MODEL` (optional, default `sonnet`) — model for the brain,
  always passed explicitly as `--model`
- `JARVIS_BRAIN_AUTOSTART` (optional, default `1`) — `0` builds the brain but
  never spawns it (every test sets this)
- `JARVIS_MUTE_MIC_DURING_SPEECH` (optional, default false) — fallback if echo
  rejection is not enough with a given microphone
- `JARVIS_TTS_BACKEND` (optional, default `say`) — `say` for the local macOS
  voice, `fish` for Fish Audio. An unknown value falls back to `say` with a
  warning: a typo in `.env` must not cost the user his voice
- `JARVIS_TTS_VOICE` (optional, default `Daniel`) — the **`say`** voice: any
  name `say -v '?'` lists. `say -v Bogus` exits 0 and quietly uses the system
  default, so preflight checks the name against that listing and warns
- `JARVIS_TTS_RATE` (optional) — words per minute for `say`; unset is the
  voice's own
- `JARVIS_PIPER_VOICE` (optional, default `en_GB-alan-medium`) — the **piper**
  voice: a model name resolved inside `data_paths.voices_dir()`, or an
  outright path. Its own variable rather than sharing `JARVIS_TTS_VOICE`, so
  switching backend and back does not leave "Daniel" naming a piper model.
  Over HTTP only a bare NAME may be stored — onnxruntime executes what it
  loads
- `JARVIS_PIPER_BIN` (optional) — where `piper` is. Not settable through the
  API (it names a program JARVIS runs). By default JARVIS looks beside
  `sys.executable` FIRST: the server runs as `.venv/bin/python server.py`
  without the venv activated, so `which piper` finds nothing while
  `.venv/bin/piper` is right there
- `FISH_API_KEY` (optional) — Fish Audio TTS, read only when the backend is
  `fish`. JARVIS speaks without it
- `FISH_VOICE_ID` (optional) — Voice model ID, with the fish backend
- `USER_NAME` (optional) — Your name for JARVIS to use
- `JARVIS_DATA_DIR` (optional) — Where JARVIS writes everything: the SQLite
  database, memory Markdown, usage.json, the tool token. Defaults to `data/`
  (`data_paths.py`). Set it to run an isolated instance without touching live
  data — the test suite gives every test a fresh one this way.
- `JARVIS_SKIP_PERMISSIONS` (optional) — Defaults to true; passes
  `--dangerously-skip-permissions` to spawned runs, which have no TTY to
  answer a permission prompt
- `WEATHER_LOCATION_LABEL` / `WEATHER_LATITUDE` / `WEATHER_LONGITUDE` /
  `WEATHER_UNIT` (all optional) — override the auto-detected (public-IP)
  weather location and units
- `JARVIS_ALLOWED_ORIGINS` (optional) — extra origins the web boundary
  accepts, comma-separated. Only needed when the page is opened at an
  address JARVIS does not serve from itself (a LAN IP, a tunnel). Their
  host names are also what the `Host` check accepts, so a `.local` or
  tailscale name has to be listed here to work at all
- `JARVIS_DEBUG_DOCS` (optional, default off) — serve `/docs`, `/redoc` and
  `/openapi.json`. That console has a "Try it out" button on every route
- `JARVIS_ENV_FILE` (optional) — where the settings endpoints read and write
  `.env`. Defaults to the repo's own; the test suite redirects it so no test
  can rewrite the developer's real configuration
- `JARVIS_PORT` (optional, default `8340`) — set from `--port` by `main()`.
  `frontend/vite.config.ts` hard-codes 8340, so moving it breaks the dev proxy
- `JARVIS_RUN_MODEL` (optional, default `sonnet`) — model for spawned runs.
  Like the brain's, it is always emitted as an explicit `--model`; the CLI's
  own default is never relied on
- `JARVIS_PROJECTS_DIR` (optional, default `~/Projects`) — where
  `project_maker.py` may create directories, and the root paths are validated
  against. `JARVIS_PROJECT_ROOTS` overrides what counts as "inside a project"
  for the scan, and `JARVIS_SCAN_BUDGET` / `JARVIS_SCAN_CACHE` bound it
- `JARVIS_CLAUDE_PATH` (optional) — the `claude` binary spawned for the brain
  and every run. Together with `JARVIS_PROJECT_ROOTS` it is why the settings
  endpoints validate `.env` writes: a newline in a value would let a POSTed
  preference redirect the binary JARVIS executes
- `JARVIS_CLAUDE_CONFIG_DIRS` (optional) — extra Claude config roots beyond
  `~/.claude` and `~/.claude-orcha`, for session watching and usage scanning
- `JARVIS_BIND_HOST` / `JARVIS_SCHEME` are set by `main()` from `--host` and
  whether the certs exist; the web boundary reads them. Set the flags, not
  these

## Testing
Run the suite as:

```bash
pytest
```

No flags. `pytest.ini` sets `testpaths` and deselects `-m "not browser"`, so a
bare run is the whole suite and touches neither the network nor the screen.

`tests/test_browser_integration.py` is marked `browser` (one `pytestmark` for
the file) because it drives `browser.py`, which launches Chromium with
`headless=False` on purpose and runs live searches. Run those with
`pytest -m browser`; they skip themselves if there is no network.

Everything else uses fakes at the subprocess seam — `screencapture`, `sips`,
`osascript` and `claude` are never really invoked. If you add a test that
needs the network, a real window, or a real `claude`, mark it.

One file, or one test:

```bash
pytest tests/test_run_store.py
pytest tests/test_run_store.py::test_name -x
```

`tests/conftest.py` puts autouse fixtures between every test and the
developer's real machine: `JARVIS_BRAIN_AUTOSTART=0`, a tmp `JARVIS_DATA_DIR`,
`JARVIS_ENV_FILE` and `JARVIS_PROJECTS_DIR`, and a `notifier.notify` that
raises. Do not defeat them — a test that needs its own root still sets the
variable itself.

The frontend is part of the gate. CI (`.github/workflows/tests.yml`, macOS,
Python 3.12) runs these before pytest, so run them after touching
`frontend/`:

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Python 3.11+ is required — the code uses `X | None` at runtime, so the
`python3` macOS ships with dies at import.

## Pull requests
Every PR goes to **`kenhayward/jarvis`** (the `origin` remote), never to
`ethanplusai/jarvis` (`upstream`). `gh pr create` defaults a fork's base to
the parent repository, so the base is always passed explicitly:

```bash
gh pr create --repo kenhayward/jarvis --base main
```

## Conventions
- JARVIS personality: British butler, dry wit, economy of language
- Max 1-2 sentences per voice response
- The brain reaches JARVIS's capabilities as MCP tools (`jarvis_mcp.py` ->
  `/internal/tool`), not by parsing `[ACTION:X]` tags out of its reply — that
  tag machinery is gone in full, including the last handler (`_execute_browse`),
  which lost its caller with the voice dispatch chain
- AppleScript for Terminal and Chrome control (no OAuth needed)
- A platform that cannot do something **withdraws the tool, it never fakes
  it**. A tool that always answers "not supported here" is described to the
  brain every turn at ~250 tokens, invites an attempt, and gives it something
  to apologise for; a tool the brain never sees costs nothing. Portable is the
  default — a tool is only platform-bound if it is listed in
  `jarvis_platform.base.TOOL_CAPABILITIES`, so forgetting to list one leaves
  it working everywhere rather than silently dead where nobody tested
- SQLite for runs, run events and usage (`run_store.py`, `usage_store.py`);
  long-term memory is plain Markdown files instead (`jarvis_memory.py`) —
  the user edits it directly, so it is never a database
