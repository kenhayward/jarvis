"""A host with exactly the capabilities, and exactly the providers, a test asks for.

The point of this file is that the withdrawal machinery gets exercised on
macOS, where the real host declares everything and would therefore never
withdraw anything. Without it, the first proof that a tool can be taken
away cleanly would arrive on Windows, on the day the whole port depends on
it.
"""

from __future__ import annotations

from .base import ALL_CAPABILITIES, Host


def fake_host(*, name: str = "fake", capabilities=None, without=(),
              **providers) -> Host:
    """A host declaring `capabilities`, or everything minus `without`.

    Two spellings for the capability set because tests want both: "a
    machine that can only do X" and "a Mac that has lost X".

    `providers` are the sub-interfaces — `notifications=`, `launcher=`,
    `screen=`, `dialogs=`, `secrets=`. **Anything not named keeps the REAL
    host's**, not the null object. That default is deliberate and was
    learned the hard way: a test installing a recording launcher would
    otherwise silently lose `secrets` too, and every server test calls
    `ensure_tool_token` at boot — so the failure arrived nowhere near the
    provider that had actually been swapped.

    A test that genuinely wants a provider absent passes the null object
    from `base` explicitly, which also makes that intent readable.
    """
    if capabilities is None:
        capabilities = ALL_CAPABILITIES - frozenset(without)

    from . import _detect
    real = _detect()
    for field in ("notifications", "launcher", "dialogs", "screen", "secrets"):
        providers.setdefault(field, getattr(real, field))

    return Host(name=name, capabilities=frozenset(capabilities), **providers)
