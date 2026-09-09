"""How the launch prompt REACHES the brain, as distinct from what it says.

`tests/test_system_prompt_header.py` owns the content: every input to
`launch_prompt` is driven with a hostile value there. This file owns the
transport, which is a separate thing and was silently broken on Windows.

Measured on a real Windows box, 2026-09-09, against the npm install this
repository's own README tells users to do:

    npm install -g @anthropic-ai/claude-code

writes a `claude.cmd` shim rather than an executable. `create_subprocess_exec`
runs it — the long-standing belief that it cannot is wrong — but Windows
reaches a `.cmd` through the COMMAND PROCESSOR, so the argument list is
re-parsed by cmd.exe on the way in. Two things happen there that do not
happen to an `.exe`:

* a NEWLINE truncates the argument; everything after it is dropped
* `%NAME%` is expanded

`launch_prompt()` is multi-line whenever there is a handover to carry, which
is every generation after the first. Measured: 510 of 839 characters, 60% of
the system prompt, silently gone — the whole handover block and the paragraph
that frames it as untrusted.

The text is not dropped INTO anything: post-newline content is discarded, not
executed. This is data loss, not injection.

The cure is not to quote it better. `cmd.exe /c <shim>` was measured and
damages the argument identically, because that is already what happens; there
is no quoting of a newline that survives cmd.exe. The cure is that no
multi-line text may travel in argv at all, so the prompt goes to a FILE and
only its path is passed.

So the property below is deliberately stated about argv rather than about the
flag: a future author who moves the prompt somewhere else again still has to
keep it out of the command line.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

HOSTILE_HANDOVER = "we were fixing chitauri\nand %USERPROFILE% came up"


def _config(tmp_path, **kw):
    import brain
    return brain.BrainConfig(home=tmp_path / "jarvis", **kw)


def _brain_with_a_handover(tmp_path):
    """A brain whose launch prompt is MULTI-LINE, which is the only case that
    was ever broken. A cold brain with no handover is a single line and
    survived cmd.exe untouched, which is exactly why this went unnoticed."""
    import brain
    b = brain.Brain(_config(tmp_path))
    b._handover = HOSTILE_HANDOVER
    assert "\n" in b.launch_prompt(), (
        "this fixture is meant to produce a multi-line prompt; if it no "
        "longer does, the test below is passing vacuously")
    return b


# --- the property ---------------------------------------------------------

def test_no_argument_the_brain_is_launched_with_contains_a_newline(tmp_path):
    """The Windows regression, stated as the rule that prevents it.

    A newline in any argv element is truncated by cmd.exe, so an install
    that reaches `claude` through a `.cmd` shim loses everything after it.
    """
    b = _brain_with_a_handover(tmp_path)
    offenders = [a for a in b.command() if "\n" in a]
    assert not offenders, (
        f"these arguments carry a newline and would be truncated by cmd.exe "
        f"on an npm install of Claude Code: {offenders!r}")


def test_the_prompt_travels_as_a_file_not_as_an_argument(tmp_path):
    b = _brain_with_a_handover(tmp_path)
    cmd = b.command()
    assert "--append-system-prompt" not in cmd, (
        "the prompt is back in argv; see this module's docstring")
    assert "--append-system-prompt-file" in cmd


def test_the_file_holds_the_launch_prompt_verbatim(tmp_path):
    """Transport must not be lossy: what the file holds is what
    `launch_prompt()` built, to the character."""
    b = _brain_with_a_handover(tmp_path)
    expected = b.launch_prompt()
    cmd = b.command()
    written = Path(cmd[cmd.index("--append-system-prompt-file") + 1])
    assert written.read_text(encoding="utf-8") == expected


def test_the_prompt_file_is_not_inside_the_brains_own_home(tmp_path):
    """The brain's home is its cwd. A scaffolding file dropped in there is
    something it can read, list and be confused by; it belongs beside the
    home, not in it."""
    b = _brain_with_a_handover(tmp_path)
    cmd = b.command()
    written = Path(cmd[cmd.index("--append-system-prompt-file") + 1]).resolve()
    home = Path(b.config.home).resolve()
    assert home not in written.parents, (
        f"{written} is inside the brain's own home {home}")


def test_utf8_survives_the_file(tmp_path):
    """The persona and the prompt are full of em-dashes, and the default
    encoding on Windows is cp1252 — the defect that was 432 errors in phase 1.
    Pinned here so this file cannot reintroduce it."""
    b = _brain_with_a_handover(tmp_path)
    b._handover = "an em-dash — and a quote “curly” and an ellipsis …"
    expected = b.launch_prompt()
    cmd = b.command()
    written = Path(cmd[cmd.index("--append-system-prompt-file") + 1])
    assert written.read_text(encoding="utf-8") == expected
    assert "—" in written.read_text(encoding="utf-8")


# --- lifecycle ------------------------------------------------------------

def test_each_generation_gets_its_own_file(tmp_path):
    """A rotation holds the predecessor alive while the successor spawns.
    One path rewritten under two processes is a race for no benefit."""
    b = _brain_with_a_handover(tmp_path)
    first = b.command()[b.command().index("--append-system-prompt-file") + 1]
    b.generation += 1
    second = b.command()[b.command().index("--append-system-prompt-file") + 1]
    assert first != second


def test_stale_generations_are_swept(tmp_path):
    """The current one and its predecessor are live during a rotation.
    Anything older is litter and must not accumulate for the life of the
    process."""
    b = _brain_with_a_handover(tmp_path)
    paths = []
    for _ in range(5):
        b.generation += 1
        cmd = b.command()
        paths.append(Path(cmd[cmd.index("--append-system-prompt-file") + 1]))

    assert paths[-1].exists(), "the current generation's prompt must be there"
    assert paths[-2].exists(), "the predecessor is still running; keep its file"
    stale = [p for p in paths[:-2] if p.exists()]
    assert not stale, f"these should have been swept: {stale!r}"
