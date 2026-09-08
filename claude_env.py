"""The environment every Claude Code child of JARVIS is given.

There is exactly one rule and it is a billing rule: JARVIS's Claude Code
children run on the user's **subscription**, never on an API key. The CLI
prefers an inherited `ANTHROPIC_API_KEY` over the login without saying so —
`claude auth status` still reports `loggedIn: true` while `apiKeySource`
quietly flips to the env key and the account's email and organisation go
blank — so a key in the environment silently moves every spawned run onto
paid API billing.

`server.py` loads `.env` into `os.environ` at import, and a developer's
`.env` legitimately holds `ANTHROPIC_API_KEY` for the older lookup paths.
That is how the key reaches a child that never wanted it.

This module exists so the scrub is written once. It was fixed for the brain
during milestone 1 and NOT for the run pipeline, which is precisely the
failure mode a second copy of the logic produces: the copy that was not
updated is the one nobody notices.
"""

from __future__ import annotations

import os
import shlex

# Every ANTHROPIC_* variable, not just the key: the base URL and the model
# override redirect a child just as effectively as credentials do.
SCRUBBED_ENV_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_")
SCRUBBED_ENV_KEYS = {"CLAUDECODE"}

# asyncio.create_subprocess_exec gives a child's stdout/stderr StreamReader a
# 64 KiB *line* buffer by default (asyncio.streams._DEFAULT_LIMIT). `claude -p
# --output-format stream-json` emits one JSON object per line, and a single
# line carrying a large tool result (a big file read, a long assistant
# message, a large diff) routinely exceeds that. When it does, `readline()`
# raises `ValueError("Separator is not found, and chunk exceed the limit")` —
# which, uncaught, killed an otherwise-healthy run (run_executor.py) or the
# brain process (brain.py) outright. A run that had been working for 28
# minutes was recorded as `failed` in 0 seconds because of exactly this.
#
# This is a buffer *ceiling*, not a pre-allocation: asyncio grows the
# underlying bytearray as data arrives, so a generous limit costs nothing
# while idle. 64 MiB is comfortably larger than any single stream-json line
# JARVIS has observed in practice (the worst offenders are full-file Read
# results and large diffs, which top out in the low single-digit MiB) while
# staying small enough that even a runaway line cannot balloon memory
# unboundedly — pass this to every `create_subprocess_exec(..., limit=...)`
# that reads a Claude Code child's stdout/stderr.
STREAM_LINE_LIMIT = 64 * 1024 * 1024  # 64 MiB per line


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """A copy of the environment with everything that would redirect or
    re-bill a Claude Code child removed. Everything else — PATH, HOME,
    CLAUDE_CONFIG_DIR, the user's own variables — passes through untouched."""
    source = os.environ if base is None else base
    return {k: v for k, v in source.items()
            if not k.startswith(SCRUBBED_ENV_PREFIXES)
            and k not in SCRUBBED_ENV_KEYS}


def split_command(spec: str) -> list[str]:
    """Split a configured program spec — `JARVIS_CLAUDE_PATH`, or whatever
    `shutil.which` found — into an argv list.

    The spec may be a bare program name, a path, or a path followed by
    arguments; the third form is why this is a split at all rather than a
    one-element list. `shlex.split` is right for all three on POSIX and
    destroys the second and third on Windows, because it treats backslash as
    an escape character. Measured:

        >>> shlex.split(r"C:\\nodejs\\claude.cmd")
        ['C:nodejsclaude.cmd']
        >>> shlex.split(r"C:\\Program Files\\nodejs\\claude.cmd")
        ['C:Program', 'Filesnodejsclaude.cmd']

    Every separator is eaten, and a path with a space in it is torn in two
    besides. The run then fails to spawn with an error naming a program
    nobody typed — and `JARVIS_CLAUDE_PATH` is precisely the setting a
    Windows user reaches for first, so the failure lands on the person
    already trying to work around something.

    The rule, in order:

    1. If the whole spec names a file that exists, it is one token. Exact on
       both platforms, no quoting rules involved, and it covers every spec
       that is just a path — including one with spaces in it and no quotes,
       which no splitter would get right.
    2. Otherwise, POSIX splits POSIX-style.
    3. Otherwise, Windows splits without backslash escaping and strips the
       quote pair the caller wrote around an argument, which is as close to
       CommandLineToArgvW as the standard library offers.

    NOTE for the Windows platform work: splitting is only half of it.
    `create_subprocess_exec` cannot run a `.cmd` or `.bat` directly — those
    need the command processor — so spawning a `claude.cmd` still has to be
    handled at the call sites. That is deliberately not done here; this
    function's job is to hand back what the user actually configured.
    """
    spec = (spec or "").strip()
    if not spec:
        return []

    try:
        if os.path.isfile(spec):
            return [spec]
    except (OSError, ValueError):
        pass                          # an absurd path is not a file; go split

    if os.name != "nt":
        return shlex.split(spec)

    tokens = []
    for token in shlex.split(spec, posix=False):
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            token = token[1:-1]
        if token:
            tokens.append(token)
    return tokens
