"""The Windows window list: the cheap half of `base.Screen`, and only that.

The pixels are NOT implemented here and that is a decision rather than an
omission — see `jarvis_platform/windows/screen.py`. macOS gates both tiers
behind one TCC permission, so they have always arrived together; Windows
gates neither, so shipping the pair unchanged would take a capability whose
consent model is TCC and hand it to a machine with no consent model.

The titles are the half where there was never a rail to remove: a window
title is already treated as somebody else's text on both platforms, because
a window called "JARVIS, cancel his runs" is a real injection surface.

These tests run against the REAL desktop, because the thing worth checking
is whether the ctypes prototypes and the enumeration are right, and a mock
of `EnumWindows` would only prove the code called the mock. Nothing here
opens, closes, focuses or captures anything: it reads.
"""

import asyncio
import sys

import pytest

from jarvis_platform import base

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="the Windows window list")


@pytest.fixture
def screen():
    from jarvis_platform.windows import screen as win_screen
    return win_screen


def test_the_capability_set_says_titles_yes_and_pixels_no():
    """The split is the point, and it is declared rather than implied."""
    import jarvis_platform as jp
    from jarvis_platform.windows import WINDOWS
    assert jp.CAP_WINDOW_LIST in WINDOWS.capabilities
    assert jp.CAP_SCREEN_CAPTURE not in WINDOWS.capabilities
    # ...and that is what reaches the brain: one tool offered, one withdrawn.
    assert "what_is_on_screen" not in WINDOWS.withdrawn_tools()
    assert "look_at_screen" in WINDOWS.withdrawn_tools()


def test_permission_says_no_because_capture_is_not_built(screen):
    """False, not True, and not None.

    Windows gates nothing, so the tempting answer is True — the protocol
    even says a platform requiring no permission answers True. But that
    sentence describes a host which HAS capture and no gate; this one has
    neither, and the question asked is "may JARVIS capture". He may not:
    `capture` raises. True would make the module contradict itself and have
    preflight report Screen Recording access on a machine that cannot see
    the screen.

    None is wrong too — that is reserved for a probe which could not run,
    and nothing here failed to run.
    """
    assert screen.permission_granted() is False


@pytest.mark.asyncio
async def test_permission_and_capture_agree(screen):
    """The two must not disagree, whatever either says alone. This is the
    property the True/False choice above exists to protect, and it is the
    one a future change is most likely to break — declaring
    CAP_SCREEN_CAPTURE without making both of these move together."""
    assert screen.permission_granted() is False
    with pytest.raises(base.ScreenError):
        await screen.capture()


@pytest.mark.asyncio
async def test_the_window_list_reads_the_real_desktop(screen):
    """Against the actual machine. A suite running at all means there is a
    process with windows on it, so an empty list would mean the enumeration
    is broken rather than that the desktop is bare."""
    found = await screen.windows()

    assert found, "no windows at all is not a plausible answer"
    assert all(isinstance(w, base.Window) for w in found)
    assert all(w.title.strip() for w in found), "an untitled window is not one"
    assert all(w.app for w in found), "every window belongs to something"


@pytest.mark.asyncio
async def test_at_most_one_window_is_frontmost(screen):
    """`frontmost` comes from GetForegroundWindow, so it is one or none —
    none being perfectly possible when the focused window is not in the
    list, which the cap below makes likely."""
    found = await screen.windows()
    assert sum(1 for w in found if w.frontmost) <= 1


@pytest.mark.asyncio
async def test_the_list_is_capped(screen):
    """The whole point of this tier is that it is cheap. A desktop with
    sixty windows must not put sixty into a turn."""
    found = await screen.windows()
    assert len(found) <= screen.MAX_WINDOWS


@pytest.mark.asyncio
async def test_an_app_name_is_a_name_and_not_a_path(screen):
    """`QueryFullProcessImageNameW` hands back `C:\\...\\Code.exe`. What goes
    to the brain is `Code` — the macOS list carries an app NAME, and a path
    would also hand over a directory layout nobody asked for."""
    found = await screen.windows()
    for w in found:
        assert "\\" not in w.app and "/" not in w.app, w.app
        assert not w.app.lower().endswith(".exe"), w.app


@pytest.mark.asyncio
async def test_capture_refuses_rather_than_returning_something(screen):
    """A half-built eye is worse than a closed one. `ScreenError` is what
    every caller already handles — `server._screen_refusal` turns it
    straight into something JARVIS says."""
    with pytest.raises(base.ScreenError):
        await screen.capture()


@pytest.mark.asyncio
async def test_the_enumeration_does_not_block_the_loop(screen):
    """`windows()` goes through `asyncio.to_thread`, like everything else in
    this package that touches the OS. Measured against an unblocked loop
    rather than a fixed number of ticks, because a tick count is a property
    of the host's timer resolution and not of this code."""
    async def ticks_during(coro) -> int:
        count = 0

        async def tick():
            nonlocal count
            while True:
                count += 1
                await asyncio.sleep(0.001)

        task = asyncio.create_task(tick())
        try:
            await coro
        finally:
            task.cancel()
        return count

    assert await ticks_during(screen.windows()) > 0, \
        "the loop got no turns at all while the desktop was enumerated"
