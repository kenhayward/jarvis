"""The environment and the argv every Claude Code child of JARVIS gets."""

import os
import shlex

import pytest

import claude_env


# --- child_env ------------------------------------------------------------

def test_child_env_scrubs_everything_that_would_rebill_a_child():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/Users/someone",
        "CLAUDE_CONFIG_DIR": "/Users/someone/.claude",
        "ANTHROPIC_API_KEY": "sk-should-not-survive",
        "ANTHROPIC_BASE_URL": "https://elsewhere.example",
        "CLAUDE_CODE_MESSAGING_TOKEN": "t",
        "CLAUDECODE": "1",
    }
    out = claude_env.child_env(base)
    assert out == {"PATH": "/usr/bin", "HOME": "/Users/someone",
                   "CLAUDE_CONFIG_DIR": "/Users/someone/.claude"}


# --- split_command --------------------------------------------------------
#
# The Windows half of this cannot be observed on a Mac, so the POSIX tests
# pin behaviour and the shlex tests below pin the REASON: they demonstrate
# the corruption directly, so the bug cannot quietly return by someone
# "simplifying" split_command back to shlex.split.

def test_a_bare_program_name_is_one_token():
    assert claude_env.split_command("claude") == ["claude"]


def test_a_program_with_arguments_still_splits():
    assert claude_env.split_command("claude --settings x") == \
        ["claude", "--settings", "x"]


def test_empty_and_whitespace_give_an_empty_argv():
    assert claude_env.split_command("") == []
    assert claude_env.split_command("   ") == []
    assert claude_env.split_command(None) == []


def test_a_real_path_is_one_token_even_with_spaces_in_it(tmp_path):
    """No quoting rules involved: if the whole spec IS a file, it is the
    program. This is the case that a splitter cannot get right unaided —
    an unquoted `/Program Files/claude` is two tokens to any of them."""
    directory = tmp_path / "Program Files"
    directory.mkdir()
    binary = directory / "claude"
    binary.write_text("#!/bin/sh\n")
    assert claude_env.split_command(str(binary)) == [str(binary)]
    # ...and it is genuinely ambiguous without the isfile check.
    assert len(shlex.split(str(binary))) == 2


def test_shlex_split_would_destroy_a_windows_path():
    """The defect, demonstrated rather than described.

    `shlex.split` treats backslash as an escape character, so a perfectly
    ordinary Windows path comes back with every separator eaten — and one
    containing a space is torn in two besides. The run then fails to spawn
    naming a program nobody typed, and JARVIS_CLAUDE_PATH is exactly the
    setting a Windows user reaches for first.
    """
    assert shlex.split(r"C:\nodejs\claude.cmd") == ["C:nodejsclaude.cmd"]
    assert shlex.split(r"C:\Program Files\nodejs\claude.cmd") == \
        ["C:Program", "Filesnodejsclaude.cmd"]


@pytest.mark.skipif(os.name != "nt", reason="Windows quoting rules")
def test_windows_splits_without_eating_backslashes():
    assert claude_env.split_command(r"C:\nodejs\claude.cmd --verbose") == \
        [r"C:\nodejs\claude.cmd", "--verbose"]
    assert claude_env.split_command(r'"C:\Program Files\claude.cmd" -p') == \
        [r"C:\Program Files\claude.cmd", "-p"]
