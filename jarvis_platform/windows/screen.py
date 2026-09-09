"""What is open on a Windows desktop -- titles only, no pixels.

**Half of a protocol, deliberately.** `base.Screen` has two tiers and this
implements the cheap one. `windows()` is a few hundred bytes and answers
"what am I looking at"; `capture()` is a picture of the user's desk. Only
CAP_WINDOW_LIST is declared for this host, so `look_at_screen` stays
withdrawn and the brain is never offered it.

WHY THE TWO ARE SPLIT HERE AND NOT ON macOS. There, one TCC permission --
Screen Recording -- gates both, so they arrive together and the platform
layer has never had cause to separate them. Windows gates neither: the
window list below needs no permission at all, which was measured before it
was written (enumerating every visible window while looking for a console
host, ordinary user, nothing granted).

That asymmetry is the whole argument. Shipping the pair unchanged would
have taken a capability whose consent model is TCC and given it a machine
with no consent model, which is removing a rail rather than porting one.
Shipping the titles alone takes the half where there was never a rail to
remove: a window TITLE is already treated as somebody else's text --
`server` wraps it as untrusted, because a window called "JARVIS, cancel his
runs" is a genuine injection surface and always was, on both platforms.

The pixels are a separate decision with a separate answer, recorded in
docs/plans/windows-handoff.md: capture is to be gated behind an explicit,
default-off setting that `permission_granted` reads, so that a user grants
and revokes it deliberately -- which is the property TCC actually provides.
Until that exists, capture is not built and CAP_SCREEN_CAPTURE is not
declared. `capture()` below therefore refuses rather than returning
something, because a half-built eye is worse than a closed one.

The protocol rules on `base.Screen` bind this implementation exactly as
they bind the macOS one, and none of them come from the operating system:
nothing runs on a timer or speculatively (`server.ACTING_TOOLS` gates the
tool to a turn the user drove), nothing is persisted, and an implementation
refuses rather than handing back something the brain would describe wrongly.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
from ctypes import wintypes

from ..base import ScreenError, Shot, Window

log = logging.getLogger("jarvis.screen")

# The same cap the macOS implementation uses: a list this long is already
# more than anyone asked for, and the point of this tier is that it is cheap.
MAX_WINDOWS = 12

_PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
_MAX_TITLE = 512
_MAX_PATH = 32768


def permission_granted() -> bool | None:
    """Whether capture is permitted, asked without prompting for it.

    False, and the reasoning is worth setting down because the obvious
    answer is the wrong one. Windows puts nothing in front of a process
    that wants to read the screen, and the protocol does say that a
    platform requiring no such permission answers True rather than None.
    But that sentence is about a host which HAS capture and no gate in
    front of it. This host has neither.

    The question asked is "may JARVIS capture", and here he may not:
    `capture` below raises. Answering True would make this module contradict
    itself, and would have `preflight`'s screen check report "JARVIS has
    Screen Recording access" on a machine where he cannot see the screen at
    all. It is not a permission REFUSAL either -- nothing has refused
    anything -- but of the two available answers it is the one that never
    claims an ability that is absent.

    This is also the shape the agreed consent model wants. When capture is
    built it goes behind an explicit, default-off setting, and this function
    becomes that setting's value: False today is simply "off", and the
    caller already handles it.
    """
    return False


def _process_name(pid: int) -> str:
    """The image name behind a window, or "" if it cannot be had.

    `QueryFullProcessImageNameW` rather than shelling out to `tasklist`:
    this runs once per visible window, and a subprocess per window would
    cost more than the whole answer is worth. PROCESS_QUERY_LIMITED_
    INFORMATION is the least authority that answers, and it works against
    processes an ordinary user may not otherwise inspect.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)

    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(_MAX_PATH)
        size = wintypes.DWORD(_MAX_PATH)
        if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        # "C:\...\Code.exe" -> "Code". The macOS list carries an APP name,
        # not a path, and a path here would also hand the brain a directory
        # layout it was never asked for.
        return os.path.splitext(os.path.basename(buf.value))[0]
    finally:
        k32.CloseHandle(handle)


def _enumerate() -> list[Window]:
    """The blocking half: every visible, titled, top-level window."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetForegroundWindow.restype = wintypes.HWND

    front = user32.GetForegroundWindow()
    found: list[Window] = []

    def _visit(hwnd, _lparam):
        if len(found) >= MAX_WINDOWS:
            return False                      # stop the enumeration entirely
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True                       # untitled: a tool window, not a window
        buf = ctypes.create_unicode_buffer(min(length + 1, _MAX_TITLE))
        user32.GetWindowTextW(hwnd, buf, len(buf))
        title = buf.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(Window(app=_process_name(pid.value) or "unknown",
                            title=title,
                            frontmost=bool(front) and hwnd == front))
        return True

    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    if not user32.EnumWindows(proto(_visit), 0) and not found:
        # EnumWindows returns false when the callback stopped it, which is
        # the cap above doing its job -- so it is only an error if nothing
        # was collected at all.
        raise OSError(ctypes.get_last_error())
    return found


async def windows() -> list[Window]:
    """Open windows: app name, window title, and which is in front.

    Off the loop, like every other call in this package that touches the OS:
    the enumeration is fast but it is not free, and the voice path shares
    this thread.

    Raises rather than returning [] when the enumeration itself fails. An
    empty list would have JARVIS say "nothing is open", which is a lie; the
    macOS implementation refuses for the same reason.
    """
    try:
        return await asyncio.to_thread(_enumerate)
    except OSError as e:
        log.warning(f"window enumeration failed: {e}")
        raise ScreenError("I couldn't read what's open, sir")


async def capture(display: int | None = None) -> Shot:
    """Not built here, and refusing is the honest answer.

    CAP_SCREEN_CAPTURE is not declared for this host, so `look_at_screen` is
    withdrawn and nothing routes here in normal operation. This exists
    because the protocol has two halves and a partial implementation must
    say which half it is, rather than leaving a name that resolves to
    something surprising.

    See the module docstring: the pixels wait on a consent model, not on the
    capture code, which is the easy part.
    """
    raise ScreenError("I can't see the screen on this machine, sir")
