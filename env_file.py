"""The ONE definition of what a line of `.env` is.

Standard library only: install.py reads `.env` with it before the venv
exists, and must read it exactly as the server does.

Every reader uses it -- server.py's boot loader and `_read_env`, and
`_env_value_problem`, which is what the settings writer asks before it puts
a value on a line. One function rather than three copies because the copies
disagreed. The writer forbade three characters -- "\\n", "\\r", "\\0" -- and
`str.splitlines()` splits on ten, so `{"user_name": "Tony\\x0bJARVIS_CLAUDE_PATH=/tmp/evil"}`
came back 200 and `_read_env()` then reported JARVIS_CLAUDE_PATH=/tmp/evil.
That is the binary the brain is spawned from, and /api/restart is one call
away. Extending the blocklist to ten characters would have left the same
shape of bug for the next separator; deriving the writer's rule from the
reader's parser cannot.
"""


def parse_env_lines(text: str) -> list[tuple[str, str]]:
    """Every (key, value) a reader of `.env` sees in `text`, in order."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out.append((k.strip(), v.strip().strip('"').strip("'")))
    return out
