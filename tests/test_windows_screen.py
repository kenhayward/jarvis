"""The Windows screen: both tiers of `base.Screen`, against the real desktop.

The window list came first and the pixels a commit later, and the gap was
the point. macOS gates both behind one TCC permission, so they have always
arrived together; Windows gates NEITHER, so shipping the pair unchanged
would have taken a capability whose consent model is TCC and handed it to a
machine with no consent model. The titles were the half where there was
never a rail to remove: a window title is already treated as somebody else's
text on both platforms, because a window called "JARVIS, cancel his runs" is
a real injection surface.

The rail for the pixels is rebuilt as JARVIS's own switch,
`JARVIS_SCREEN_CAPTURE`, shipped OFF. Most of what is tested here is that
switch — the capture either works or it does not and the machine will say
which, whereas whether a refusal is honest is the part that can rot quietly.

These tests run against the REAL desktop, because what is worth checking is
whether the ctypes prototypes, the enumeration and the PowerShell script are
right, and a mock of `EnumWindows` would only prove the code called the
mock. Nothing here opens, closes or focuses anything: it reads, and — with
the gate deliberately switched on by the test itself — it photographs.
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


def test_the_capability_set_declares_both_tiers():
    """Both are built now, so both are declared — and `look_at_screen` is
    offered to the brain even though the switch defaults to OFF.

    That is not a hole in "withdraw, never fake". A capability answers "is
    this built on this host"; the switch answers "may he, today". macOS
    declares CAP_SCREEN_CAPTURE while TCC is free to refuse every call, and
    this is the same shape. Making the capability follow the switch would
    also mean the brain could never be told the switch exists — the tool
    would simply vanish, and "turn screen capture on in Settings" is the one
    useful thing to say to somebody asking JARVIS to look at their screen.
    """
    import jarvis_platform as jp
    from jarvis_platform.windows import WINDOWS
    assert jp.CAP_WINDOW_LIST in WINDOWS.capabilities
    assert jp.CAP_SCREEN_CAPTURE in WINDOWS.capabilities
    assert "what_is_on_screen" not in WINDOWS.withdrawn_tools()
    assert "look_at_screen" not in WINDOWS.withdrawn_tools()


def test_the_switch_is_off_unless_it_says_otherwise(screen, monkeypatch):
    """The default IS the consent model. Windows asks nobody before a
    program reads the screen, so an absent setting has to mean no — if it
    ever came to mean yes, JARVIS would have quietly acquired an eye on the
    user's desk that nobody switched on.
    """
    monkeypatch.delenv(screen.CAPTURE_ENV, raising=False)
    assert screen.permission_granted() is False
    for junk in ("", "  ", "0", "false", "no", "off", "maybe", "TRUE-ish"):
        monkeypatch.setenv(screen.CAPTURE_ENV, junk)
        assert screen.permission_granted() is False, junk


def test_the_switch_reads_the_ordinary_spellings_of_yes(screen, monkeypatch):
    for yes in ("1", "true", "TRUE", "yes", "on", " true "):
        monkeypatch.setenv(screen.CAPTURE_ENV, yes)
        assert screen.permission_granted() is True, yes


def test_permission_is_never_none_here(screen, monkeypatch):
    """None means "the probe could not be run", and reading a setting cannot
    fail. Saying None would have preflight report "could not determine"
    about a value sitting in `os.environ`."""
    monkeypatch.delenv(screen.CAPTURE_ENV, raising=False)
    assert screen.permission_granted() is not None
    monkeypatch.setenv(screen.CAPTURE_ENV, "true")
    assert screen.permission_granted() is not None


@pytest.mark.asyncio
async def test_a_capture_with_the_switch_off_is_refused(screen, monkeypatch):
    """`permission_granted` and `capture` must never disagree — a capture
    that worked while the setting said no would make the whole consent model
    decorative. This is the property most likely to break next."""
    monkeypatch.delenv(screen.CAPTURE_ENV, raising=False)
    with pytest.raises(base.ScreenError) as caught:
        await screen.capture()
    said = str(caught.value)
    assert "switched off" in said, "and it says WHY, so the user can act"
    assert "Settings" in said


@pytest.mark.asyncio
async def test_a_capture_with_the_switch_on_photographs_the_whole_desktop(
        screen, monkeypatch):
    """The real thing, against the real screen — and the assertion that
    matters is the SIZE.

    Without `SetProcessDPIAware` a process is lied to about the display:
    measured on this box, 1536x960 reported against 3840x2400 physical, so
    `CopyFromScreen` copies the top-left corner — 16% of the desktop by
    area. The result is a real, plausible, correctly-shaped screenshot of
    the wrong thing, which JARVIS would describe as "your screen".

    THE RESULT CANNOT BE ASSERTED ON, and finding that out is why the guard
    in `_refuse_a_partial_desktop` exists. The first version of this test
    compared the shot's dimensions and aspect ratio against the physical
    display — and passed with the DPI line deleted, because both a whole
    3840x2400 desktop and a 1536x960 corner of it shrink to exactly 1280x800
    under the cap, and a crop of a 16:10 screen is still 16:10.

    So what is asserted is that the capture is whole, which only the SOURCE
    bounds can say. Deleting the DPI line now raises rather than lying, and
    `test_a_partial_desktop_is_refused_rather_than_described` below drives
    that refusal directly.
    """
    monkeypatch.setenv(screen.CAPTURE_ENV, "true")

    shot = await screen.capture()

    assert shot.png.startswith(b"\x89PNG"), "a PNG, not whatever was on disk"
    assert max(shot.width, shot.height) <= screen.SHOT_MAX_EDGE
    assert len(shot.png) <= screen.MAX_SHOT_BYTES

    physical = screen._primary_physical_size()
    assert physical is not None, "this box can report its own display size"
    ratio = shot.width / shot.height
    assert abs(ratio - physical[0] / physical[1]) < 0.02, (
        f"captured {shot.width}x{shot.height} from a {physical} display")


def test_a_partial_desktop_is_refused_rather_than_described(screen):
    """The guard itself, driven with the bounds the DPI bug produces.

    A capture that covered 1536x960 of a 3840x2400 display is exactly what a
    non-DPI-aware process returns, and it must raise rather than reach the
    brain — "I could only see part of your screen" is a worse answer than a
    picture only in the sense that it is shorter. It is a far better one
    than a confident description of the wrong 16%.
    """
    physical = screen._primary_physical_size()
    assert physical is not None

    # Whole: allowed.
    screen._refuse_a_partial_desktop(f"{physical[0]}x{physical[1]}\n", None)

    # A corner: refused.
    with pytest.raises(base.ScreenError) as caught:
        screen._refuse_a_partial_desktop(
            f"{physical[0] * 2 // 5}x{physical[1] * 2 // 5}\n", None)
    assert "part of your screen" in str(caught.value)


def test_the_partial_guard_stands_down_when_it_cannot_know(screen, monkeypatch):
    """Two cases where refusing would be worse than proceeding.

    A second monitor is legitimately a different shape from the primary, and
    the physical size read here is the PRIMARY one — so a capture of display
    2 is not something this guard can judge. And a script that reported
    nothing readable has told us nothing, which is not the same as telling us
    the capture was partial. Refusing a capture that would have been fine is
    its own failure.
    """
    screen._refuse_a_partial_desktop("1x1\n", display=2)
    screen._refuse_a_partial_desktop("not a size at all", None)
    screen._refuse_a_partial_desktop("", None)

    monkeypatch.setattr(screen, "_primary_physical_size", lambda: None)
    screen._refuse_a_partial_desktop("1x1\n", None)


@pytest.mark.asyncio
async def test_a_display_that_is_not_there_says_so(screen, monkeypatch):
    """Rather than quietly handing back the primary one, which would answer
    a question nobody asked and look right while doing it."""
    monkeypatch.setenv(screen.CAPTURE_ENV, "true")
    with pytest.raises(base.ScreenError) as caught:
        await screen.capture(display=99)
    assert "no display 99" in str(caught.value)


@pytest.mark.asyncio
async def test_the_capture_leaves_nothing_on_disk(screen, monkeypatch):
    """A photograph of the user's desk lives as long as it takes to read the
    bytes and no longer. A protocol rule from `base.Screen`, not either
    platform's habit."""
    import tempfile
    from pathlib import Path
    monkeypatch.setenv(screen.CAPTURE_ENV, "true")
    root = Path(tempfile.gettempdir())
    before = set(root.glob("jarvis-screen-*"))
    await screen.capture()
    assert set(root.glob("jarvis-screen-*")) <= before


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
