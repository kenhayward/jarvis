"""Windows notifications -- the fallback when no browser tab is listening.

**Written from documentation, not from measurement** -- and of everything in
this package, this is the piece most likely to need correcting on a real
box. Windows toasts are fiddly in ways that are invisible until you try
them: an unregistered AUMID makes `Show()` succeed and display nothing,
and Focus Assist silently drops what does get through. That is survivable
here, because a notification is a fallback and `notify()` reporting False
means "nobody was told", which the announcement path already handles. It
must never become an exception -- see `server._announce_needs_you`.

**The argv discipline from the macOS implementation carries over, and it is
the reason this file looks the way it does.** Titles and messages come from
another Claude Code session's transcript -- text JARVIS did not write. The
macOS version never lets that text into the script SOURCE: the script is
fixed, read from stdin, and the values arrive as argv, which osascript
hands over as data.

PowerShell has no argv for a script read from stdin, so the same property
is bought a different way: **the values go in the child's ENVIRONMENT**, and
the fixed script reads `$env:...`. An environment variable is data on both
sides -- there is no parse step to get wrong, and a value containing
`"; Remove-Item -Recurse C:\\ #` is just a string with those characters in
it. There is no escaping function here for the same reason there is none in
the macOS version: there is nothing to escape.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

log = logging.getLogger("jarvis.platform.notifications")

# A notification is a glance, not an essay. Same bounds as the macOS side.
_TITLE_MAX = 120
_SUBTITLE_MAX = 120
_MESSAGE_MAX = 300

# PowerShell is slower to start than osascript (a few hundred ms against a
# few tens), and this runs while the user is waiting on nothing at all, so
# the ceiling is generous. A wedged one must still not hang the caller.
_TIMEOUT_SECONDS = 15.0

# The application identity a toast is shown under. An AUMID that is not
# registered on the machine makes `Show()` succeed and display NOTHING,
# which is the failure this constant exists to make correctable in one
# place. PowerShell's own is used because it is registered wherever
# PowerShell is, which is everywhere this code can run at all.
_AUMID = (r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
          r"\WindowsPowerShell\v1.0\powershell.exe")

# Environment variable names, not script placeholders. See the module
# docstring for why that distinction is the whole design.
_ENV_TITLE = "JARVIS_TOAST_TITLE"
_ENV_MESSAGE = "JARVIS_TOAST_MESSAGE"
_ENV_SUBTITLE = "JARVIS_TOAST_SUBTITLE"

# Fixed script. No untrusted text ever enters this string; the three values
# are read from the environment as data.
_NOTIFY_SCRIPT = f"""\
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$type = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($type)
$nodes = $xml.GetElementsByTagName('text')
$heading = $env:{_ENV_TITLE}
if ($env:{_ENV_SUBTITLE}) {{ $heading = $heading + ' - ' + $env:{_ENV_SUBTITLE} }}
$nodes.Item(0).AppendChild($xml.CreateTextNode($heading)) | Out-Null
$nodes.Item(1).AppendChild($xml.CreateTextNode($env:{_ENV_MESSAGE})) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_AUMID}').Show($toast)
"""


def _truncate(text: str, limit: int) -> str:
    """Bound text length for a glanceable notification, marking any cut."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "\u2026"


def _powershell() -> str | None:
    """Where PowerShell is, preferring the one that ships with Windows.

    `powershell.exe` (5.1, in System32) rather than `pwsh` (7+, installed
    separately): the WinRT projection the script above uses is present in
    the shipped one and needs a compatibility module in the newer one.
    """
    return shutil.which("powershell.exe") or shutil.which("powershell")


def available() -> bool:
    """Whether posting a notification is plausible right now.

    Cheap and side-effect free: Windows, plus PowerShell on PATH. A
    precondition check and not a delivery guarantee -- Focus Assist, an
    unregistered AUMID, or notification settings can still swallow it.
    """
    return os.name == "nt" and _powershell() is not None


async def notify(title: str, message: str, *, subtitle: str = "") -> bool:
    """Post a toast. Returns whether it was handed off successfully.

    Never raises: any failure is logged and reported as False. This is the
    path taken when nobody is listening on the voice channel, so it must
    not be able to break the announcement it is standing in for.
    """
    try:
        shell = _powershell()
        if not available() or shell is None:
            log.warning("notifications: unavailable on this platform")
            return False

        env = dict(os.environ)
        env[_ENV_TITLE] = _truncate(str(title or ""), _TITLE_MAX)
        env[_ENV_MESSAGE] = _truncate(str(message or ""), _MESSAGE_MAX)
        env[_ENV_SUBTITLE] = _truncate(str(subtitle or ""), _SUBTITLE_MAX)

        try:
            proc = await asyncio.create_subprocess_exec(
                shell, "-NoProfile", "-NonInteractive", "-Command", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env)
        except OSError as e:
            log.warning("notifications: failed to spawn PowerShell: %s", e)
            return False

        try:
            _out, err = await asyncio.wait_for(
                proc.communicate(_NOTIFY_SCRIPT.encode("utf-8")),
                timeout=_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            log.warning("notifications: PowerShell timed out, killing it")
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            return False

        if proc.returncode != 0:
            log.warning("notifications: PowerShell exited %s: %s",
                        proc.returncode,
                        err.decode("utf-8", "replace").strip()[:200])
            return False
        return True
    except Exception as e:
        # Belt and braces: this path must never raise into the caller.
        log.warning("notifications: unexpected error: %s", e)
        return False
