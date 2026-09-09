"""What is open on a Windows desktop, and -- if the user allows it -- a picture.

**Both tiers of `base.Screen`, but they arrived a commit apart, and the gap
was the point.** `windows()` is a few hundred bytes and answers "what am I
looking at"; `capture()` is a photograph of the user's desk. macOS gates
both behind ONE TCC permission, so they have always arrived together and the
platform layer never had cause to separate them -- a fact about TCC, not
about the tiers.

Windows gates NEITHER. Nothing is asked before a program enumerates windows
or reads the screen, and that asymmetry is the whole argument. The titles
shipped first because that is the half where there was never a rail to lose:
enumerating windows needs no permission here (measured before it was
written), and a window TITLE was already treated as somebody else's text on
both platforms -- `server` wraps it untrusted, because a window called
"JARVIS, cancel his runs" is a genuine injection surface and always was.

The pixels waited for a consent model, because shipping them unchanged would
have taken a capability whose model on macOS is TCC and handed it to a
machine with no model at all. That is removing a rail, not porting one.

**The rail, rebuilt: `JARVIS_SCREEN_CAPTURE`, and it ships OFF.** Not a
prompt -- Windows has nothing to prompt with, and a dialog JARVIS invented
would be imitating consent rather than having it. What is reproduced is the
one property of TCC worth reproducing: an explicit switch the user turns on,
and can turn off again, outside any conversation. `permission_granted()`
reads it at CALL time, so both the grant and the revocation take effect on
the next capture rather than the next restart.

CAP_SCREEN_CAPTURE is declared even so, because the capability answers "is
this built here" and the setting answers "may he, today" -- exactly as macOS
declares it while TCC may still say no. Withdrawing the tool on the value of
a switch would also mean the brain could not be told the switch exists.

The protocol rules on `base.Screen` bind this implementation exactly as they
bind the macOS one, and none of them come from the operating system: nothing
runs on a timer or speculatively (`server.ACTING_TOOLS` gates the tool to a
turn the user drove), nothing is persisted, and an implementation refuses
rather than handing back something the brain would describe wrongly.

Written from documentation is how this package began; this module is no
longer that. The window list was measured on a real box, and so was the
capture -- including the DPI trap recorded at `_CAPTURE_PS1`, which produced
a perfectly plausible screenshot of the wrong 16% of the desktop.
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import logging
import os
import shutil
import struct
import tempfile
from ctypes import wintypes
from pathlib import Path

from ..base import CaptureGate, ScreenError, Shot, Window

log = logging.getLogger("jarvis.screen")

# The same cap the macOS implementation uses: a list this long is already
# more than anyone asked for, and the point of this tier is that it is cheap.
MAX_WINDOWS = 12

# The same bounds as macOS, and for the same reasons -- images are charged by
# AREA, so a 4K capture is thousands of tokens off one turn. This machine's
# display is 3840x2400, which would be ~12,300 tokens; at 1280 it is ~1,200.
SHOT_MAX_EDGE = 1280
MAX_SHOT_BYTES = 4_000_000

# Measured on a real box: 0.71s warm, 2.30s on the run where PowerShell said
# "Preparing modules for first use". The budget is generous because that
# preparation is the variable part and a capture the user asked for is worth
# waiting for -- but it stays well inside `jarvis_mcp.TIMEOUT_SEC` (20s),
# which is what a caller would otherwise report as the server being
# unreachable while the work carried on.
CAPTURE_TIMEOUT_SEC = 15.0

# The setting that stands where TCC stands on macOS. Off unless it says
# otherwise, and read at CALL time rather than at import, so granting it
# takes effect on the next capture rather than on the next restart --
# `server._write_env_key` updates `os.environ` as well as `.env`.
CAPTURE_ENV = "JARVIS_SCREEN_CAPTURE"
_TRUE_VALUES = ("1", "true", "yes", "on")

_NO_PERMISSION = (
    "screen capture is switched off, sir -- you can turn it on in Settings")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
_MAX_TITLE = 512
_MAX_PATH = 32768
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


CAPTURE_GATE = CaptureGate(
    name="screen capture",
    # The field that decides a STATUS rather than only a sentence. Off is
    # the SHIPPED state here, not a fault, so preflight warns (logged) where
    # macOS fails (spoken). A default-off setting that made JARVIS announce
    # a failure at every boot would be nagging the user about a decision the
    # project made for them.
    off_by_default=True,
    remedy=("Windows asks nobody before a program reads the screen, so this "
            "gate is JARVIS's own and it ships OFF. Set "
            "JARVIS_SCREEN_CAPTURE=true in .env, or turn screen capture on "
            "in Settings, and it applies to the next capture -- no restart. "
            "Unset it and the eyes close again."))


def permission_granted() -> bool | None:
    """Whether capture is permitted, asked without prompting for it.

    The value of a JARVIS setting, and never a question put to Windows --
    because Windows has no answer to give. It asks nobody before a program
    reads the screen: there is no TCC here, nothing to grant, and nothing
    the user could revoke from outside JARVIS.

    That absence is the whole reason this function exists in this form.
    Shipping capture with no gate would have taken a capability whose
    consent model on macOS is TCC and handed it to a machine with no consent
    model, which is removing a rail rather than porting one. So the rail is
    rebuilt as the one property of TCC worth reproducing: an explicit switch,
    OFF until the user sets it, revocable by the same hand that set it.

    It is deliberately NOT a prompt. Windows has nothing to prompt with, and
    a dialog JARVIS invented would be imitating consent rather than having
    it -- besides breaking this function's contract, which forbids putting
    anything in front of the user.

    Never None. None means "the probe could not be run", and reading a
    setting cannot fail; saying None here would tell `preflight` to report
    "could not determine" about a value sitting in `os.environ`.
    """
    return os.environ.get(CAPTURE_ENV, "").strip().lower() in _TRUE_VALUES


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


# ── the picture ────────────────────────────────────────────────────────────

# Windows ships no `screencapture`, so the OS's own imaging is reached
# through PowerShell -- the same shape as macOS shelling out, and no new
# dependency: System.Windows.Forms and System.Drawing are .NET Framework
# assemblies present on every Windows that has PowerShell.
#
# THE FIRST TWO LINES ARE THE WHOLE POINT, and they were found by looking at
# the output rather than by reading documentation. Without SetProcessDPIAware
# a process is lied to about the screen: on this box, measured, a
# non-DPI-aware process is told the primary display is 1536x960 when it is
# physically 3840x2400 (250% scaling). `CopyFromScreen` then copies
# 1536x960 PHYSICAL pixels from the top-left corner -- 16% of the desktop by
# area -- and the result is a real, plausible, correctly-sized screenshot of
# the wrong thing, which JARVIS would have described as "your screen". That
# is this project's worst failure mode, not its most obvious one.
#
# NOTHING IS INTERPOLATED INTO THIS SCRIPT. It is a constant, and its three
# inputs arrive in the environment. That removes quoting from the problem
# entirely -- no path, however spelled, can end a string or start a command --
# and it is why the script may be read as literally as it is written.
# `-EncodedCommand` (base64 UTF-16LE) carries it past cmd.exe's parsing for
# the same reason.
#
# Do NOT rebuild this with an f-string. PowerShell's `{0}` placeholders and
# script blocks collide with str.format, which silently turned a debug line
# into "bounds 0x1" while this was being written.
_CAPTURE_PS1 = """
$ErrorActionPreference = "Stop"
Add-Type -Name Dpi -Namespace Jarvis -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][Jarvis.Dpi]::SetProcessDPIAware()
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$which = $env:JARVIS_SHOT_DISPLAY
if ([string]::IsNullOrEmpty($which)) {
  $screen = [System.Windows.Forms.Screen]::PrimaryScreen
} else {
  $all = [System.Windows.Forms.Screen]::AllScreens
  $i = [int]$which - 1
  if ($i -lt 0 -or $i -ge $all.Length) { throw "no display $which" }
  $screen = $all[$i]
}

$b = $screen.Bounds
Write-Output ([string]$b.Width + "x" + [string]$b.Height)
$full = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($full)
try {
  $g.CopyFromScreen($b.X, $b.Y, 0, 0, $full.Size)
  $max = [int]$env:JARVIS_SHOT_MAX_EDGE
  $scale = [Math]::Min(1.0, $max / [Math]::Max($full.Width, $full.Height))
  $w = [Math]::Max(1, [int]($full.Width * $scale))
  $h = [Math]::Max(1, [int]($full.Height * $scale))
  $small = New-Object System.Drawing.Bitmap $full, (New-Object System.Drawing.Size $w, $h)
  try {
    $small.Save($env:JARVIS_SHOT_PATH, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $small.Dispose() }
} finally {
  $g.Dispose()
  $full.Dispose()
}
"""


def _png_size(png: bytes) -> tuple[int, int] | None:
    """(width, height) out of a PNG's IHDR, or None if that is not a PNG.

    Doubles as "did PowerShell actually write a picture?" -- it can exit 0
    having written nothing of the kind.

    A near-copy of the macOS module's private one, deliberately. Hoisting it
    into `base` would mean editing the macOS file to import it, and that file
    cannot be exercised from this machine; ten lines of header parsing are a
    smaller risk than a blind edit to the platform this project runs on.
    """
    if len(png) < 24 or not png.startswith(_PNG_MAGIC) or png[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", png[16:24])
    if width <= 0 or height <= 0:
        return None
    return width, height


_DESKTOPVERTRES = 117
_DESKTOPHORZRES = 118


def _primary_physical_size() -> tuple[int, int] | None:
    """The primary display's real pixel size, or None if it cannot be had.

    `GetDeviceCaps(DESKTOPHORZRES/VERTRES)` rather than
    `GetSystemMetrics(SM_CXSCREEN)`, because it reports the PHYSICAL
    resolution whether or not the asking process is DPI-aware. The
    alternative would mean calling `SetProcessDPIAware` in the JARVIS server
    itself -- a process-wide, irreversible change made only to ask a
    question, which is too much to spend on a check.
    """
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        dc = user32.GetDC(None)
        if not dc:
            return None
        try:
            size = (gdi32.GetDeviceCaps(dc, _DESKTOPHORZRES),
                    gdi32.GetDeviceCaps(dc, _DESKTOPVERTRES))
        finally:
            user32.ReleaseDC(None, dc)
        return size if size[0] > 0 and size[1] > 0 else None
    except Exception as e:                        # pragma: no cover - defensive
        log.warning(f"could not read the physical display size: {e}")
        return None


async def _powershell(script: str, env: dict[str, str], timeout: float
                      ) -> tuple[int, str, str]:
    """Run one PowerShell script, bounded. Never raises; returns (rc, stderr).

    `-EncodedCommand` takes base64 UTF-16LE, which is what lets the script
    above be a constant with no escaping anywhere.

    Only the return code decides success. PowerShell writes CLIXML progress
    records to stderr on a perfectly successful run -- measured, this one
    emits "Preparing modules for first use" as a `#< CLIXML` blob while
    exiting 0 -- so treating a non-empty stderr as failure would refuse most
    first captures on a machine.
    """
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env},
        )
    except OSError as e:
        return -1, "", f"could not start powershell: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.communicate()
        except Exception:
            pass
        return -1, "", f"powershell timed out after {timeout}s"
    return (proc.returncode if proc.returncode is not None else -1,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"))


def _refuse_a_partial_desktop(reported: str, display: int | None) -> None:
    """Raise unless the script photographed the WHOLE primary display.

    The DPI trap at `_CAPTURE_PS1` is silent by construction: the capture
    comes back a real screenshot, correctly shaped, correctly sized, of the
    top-left corner. Nothing downstream can notice. Both a whole 3840x2400
    desktop and a 1536x960 corner of it shrink to exactly 1280x800 under the
    cap, and a crop of a 16:10 screen is still 16:10 -- so neither the
    dimensions nor the aspect ratio of the RESULT can tell them apart. That
    was learned by writing a test which asserted on both and watching it pass
    with the DPI line deleted.

    So the source bounds are checked instead, against the physical size read
    a different way. It is not a belt-and-braces check on something already
    proven; it is the only thing standing between a deleted line and JARVIS
    confidently describing 16% of somebody's screen as their screen.

    Skipped when a specific display was asked for -- the physical size read
    here is the PRIMARY one, and a second monitor is legitimately a different
    shape. Skipped too when either number cannot be had, because refusing a
    capture that would have been fine is its own failure.
    """
    if display is not None:
        return
    physical = _primary_physical_size()
    if physical is None:
        return
    try:
        wide, high = (int(n) for n in reported.strip().splitlines()[0].split("x"))
    except (ValueError, IndexError):
        log.warning(f"capture did not report its bounds: {reported.strip()[:80]!r}")
        return
    if (wide, high) != physical:
        log.warning(f"capture covered {wide}x{high} of a {physical[0]}x"
                    f"{physical[1]} display; refusing a partial desktop")
        raise ScreenError(
            "I could only see part of your screen, sir, so I'd rather not "
            "guess at the rest")


async def capture(display: int | None = None) -> Shot:
    """A PNG of one display, shrunk to `SHOT_MAX_EDGE`.

    `display` is a 1-based index, counted as macOS's `screencapture -D`
    counts them, so the same brain argument means the same thing on both.
    None is the primary display.

    Raises ScreenError -- with a sentence fit to be spoken -- rather than
    handing back something the brain would describe wrongly.

    Call this ONLY on a turn the user drove. See the module docstring: that
    is a protocol rule from `base.Screen`, and it does not come from the
    operating system, so nothing about Windows relaxes it.

    There is no blank-frame check here, and its absence is reasoned rather
    than skipped. macOS needs one because a capture WITHOUT Screen Recording
    exits 0 and returns a black or desktop-only frame -- a denial wearing a
    photograph's clothes. Windows denies nothing, so a black frame here is
    not a disguised refusal: it is a locked workstation, and "your screen is
    black" is then a true answer rather than a misleading one.
    """
    if not permission_granted():
        raise ScreenError(_NO_PERMISSION)

    workdir = Path(tempfile.mkdtemp(prefix="jarvis-screen-"))
    try:
        shot_path = workdir / "screen.png"
        env = {"JARVIS_SHOT_PATH": str(shot_path),
               "JARVIS_SHOT_MAX_EDGE": str(SHOT_MAX_EDGE),
               "JARVIS_SHOT_DISPLAY": str(display) if display else ""}
        rc, out, err = await _powershell(_CAPTURE_PS1, env, CAPTURE_TIMEOUT_SEC)
        if rc != 0 or not shot_path.exists():
            log.warning(f"screen capture failed (rc={rc}): {err.strip()[:200]}")
            if "no display" in err:
                raise ScreenError(
                    f"there's no display {display} on this machine, sir")
            raise ScreenError("I couldn't get a picture of your screen, sir")

        _refuse_a_partial_desktop(out, display)

        png = shot_path.read_bytes()
        size = _png_size(png)
        if size is None:
            log.warning("screen capture wrote something that is not a PNG")
            raise ScreenError("I couldn't get a picture of your screen, sir")

        # The shrink happens inside the script, so reaching here with an
        # oversized image means it did not do what it says. Refused rather
        # than sent: a full-size 3840x2400 capture is ~12,300 tokens off one
        # turn, which is the cost this whole tier exists to avoid.
        if max(size) > SHOT_MAX_EDGE or len(png) > MAX_SHOT_BYTES:
            log.warning(f"capture came back at {size} / {len(png)} bytes")
            raise ScreenError(
                "I couldn't get your screen down to a sensible size, sir")

        return Shot(png=png, width=size[0], height=size[1])
    finally:
        # The capture is on disk for as long as this takes and no longer.
        shutil.rmtree(workdir, ignore_errors=True)
