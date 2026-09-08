"""A host with exactly the capabilities a test asks for.

The point of this file is that the withdrawal machinery gets exercised on
macOS, where the real host declares everything and would therefore never
withdraw anything. Without it, the first proof that a tool can be taken away
cleanly would arrive on Windows, on the day the whole port depends on it.
"""

from __future__ import annotations

from .base import ALL_CAPABILITIES, Host


def fake_host(*, name: str = "fake", capabilities=None,
              without=()) -> Host:
    """A host declaring `capabilities`, or everything minus `without`.

    Two spellings because tests want both: "a machine that can only do X"
    and "a Mac that has lost X".
    """
    if capabilities is None:
        capabilities = ALL_CAPABILITIES - frozenset(without)
    return Host(name=name, capabilities=frozenset(capabilities))
