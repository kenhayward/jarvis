"""The Windows host, tested from a Mac.

Everything here mocks the one subprocess seam per module, so it runs on any
platform — which is the point. What it CANNOT prove is that the argv it
pins actually do what they claim on Windows; that needs a real box. So the
tests are written to be the correction surface: each one pins a decision,
and sample command output is quoted from documentation rather than
measurement. Replace a sample with a real one and the failure will say
exactly what has to move.

Read `jarvis_platform/windows/secrets.py`'s module docstring first.
"""

import os
import stat
import sys

import pytest

import jarvis_platform as jp
from jarvis_platform.base import PrivateFileUnsupported
from jarvis_platform.windows import WINDOWS
from jarvis_platform.windows import launcher as win_launcher
from jarvis_platform.windows import notifications as win_notify
from jarvis_platform.windows import secrets as win_secrets


# --- the host declares only what exists ------------------------------------

def test_windows_declares_only_what_it_has_an_implementation_for():
    """The capability set is the honest one, not the aspirational one. Add
    a capability in the same commit as its implementation, never before —
    the whole design fails the moment this list is a wish."""
    assert WINDOWS.capabilities == {jp.CAP_NOTIFICATIONS, jp.CAP_TERMINAL,
                                    jp.CAP_BROWSER, jp.CAP_EDITOR}


def test_windows_withdraws_the_four_tools_it_cannot_yet_do():
    assert WINDOWS.withdrawn_tools() == {
        "look_at_screen", "what_is_on_screen", "answer_dialog", "steer_session"}


def test_windows_still_offers_everything_portable():
    for tool in ("spawn_run", "start_build", "remember", "recall", "read_file",
                 "search_repo", "repo_overview", "list_sessions", "run_status",
                 "read_page", "look_at_page", "github_repo", "usage_status"):
        assert WINDOWS.allows_tool(tool) is True, tool


def test_the_unbuilt_providers_are_the_null_objects_not_a_stub():
    """Screen and dialogs have no Windows implementation, so they must be
    the base null objects — which refuse — rather than something that
    half-answers."""
    from jarvis_platform import base
    assert WINDOWS.screen is base.NO_SCREEN
    assert WINDOWS.dialogs is base.NO_DIALOGS
    assert WINDOWS.secrets is win_secrets


# --- the launcher's quoting, which is why the interface exists --------------

def test_windows_terminal_passes_the_directory_as_its_own_argument(monkeypatch):
    """`wt -d <dir>` needs no quoting of `dir` whatever it contains,
    because it is its own argv entry. That is the whole reason `terminal`
    takes cwd and command apart instead of a composed shell line."""
    monkeypatch.setattr(win_launcher.shutil, "which",
                        lambda name: r"C:\wt.exe" if name == "wt.exe" else None)
    argv = win_launcher._terminal_argv(r"C:\Program Files\my project", "")
    assert argv == [r"C:\wt.exe", "-d", r"C:\Program Files\my project"]


def test_windows_terminal_never_posix_quotes(monkeypatch):
    """`shlex.quote` here would be actively wrong — it is POSIX, and this
    is cmd.exe. A path with a space must not come back with backslashes or
    single quotes in it."""
    monkeypatch.setattr(win_launcher.shutil, "which",
                        lambda name: r"C:\wt.exe" if name == "wt.exe" else None)
    argv = win_launcher._terminal_argv(r"C:\a b\c", "npm run dev")
    assert argv == [r"C:\wt.exe", "-d", r"C:\a b\c", "cmd.exe", "/k", "npm run dev"]
    assert not any("'" in part or "\\ " in part for part in argv)


def test_windows_terminal_falls_back_to_cmd_with_a_drive_aware_cd(monkeypatch):
    """`cd` alone does not change drive on Windows; `cd /d` does. Getting
    this wrong opens a terminal in the wrong place and reports success."""
    monkeypatch.setattr(win_launcher.shutil, "which",
                        lambda name: r"C:\cmd.exe" if name == "cmd.exe" else None)
    argv = win_launcher._terminal_argv(r"D:\work\chitauri", "npm test")
    assert argv == [r"C:\cmd.exe", "/k", r'cd /d "D:\work\chitauri" && npm test']


def test_windows_editor_asks_for_the_cmd_shim_by_its_full_name(monkeypatch):
    """The Windows VS Code installer puts `code.cmd` on PATH, and a `.cmd`
    cannot be executed by `create_subprocess_exec` — the other half of the
    claude-path problem."""
    asked = []
    monkeypatch.setattr(win_launcher.shutil, "which",
                        lambda name: asked.append(name) or None)
    monkeypatch.setattr(win_launcher.os, "startfile", lambda p: None, raising=False)
    import asyncio
    asyncio.run(win_launcher.editor(r"C:\x\y.py"))
    assert asked[0] == "code.cmd"


# --- notifications keep the argv discipline, bought differently ------------

def test_untrusted_text_never_enters_the_notification_script():
    """The macOS version passes it as argv because osascript hands argv
    over as data. PowerShell has no argv for a script read from stdin, so
    the same property is bought with the environment. Either way there is
    no escaping step, because there is nothing to escape."""
    payload = '"; Remove-Item -Recurse C:\\ #'
    assert payload not in win_notify._NOTIFY_SCRIPT
    # The script reads variables, it does not carry values.
    for var in (win_notify._ENV_TITLE, win_notify._ENV_MESSAGE,
                win_notify._ENV_SUBTITLE):
        assert f"$env:{var}" in win_notify._NOTIFY_SCRIPT


# Both of the next two describe the module when it is NOT on its own
# platform, which is the state this file was written in. Run them ON Windows
# and `available()` is correctly True and `notify()` correctly hands a toast
# off, so the assertions below can only hold off-Windows — measured, on a
# real box: both returned True. Skipped rather than inverted, because the
# property each one pins (inert off-platform) is still worth pinning, and
# the Windows-side property is NOT "notify returns True": a toast handed to
# an unregistered AUMID also returns True and displays nothing. That one
# cannot be settled from a test at all — see docs/plans/windows-handoff.md.
_off_windows_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="describes the module off its own platform; on Windows both are True")


@_off_windows_only
def test_notifications_are_unavailable_off_windows():
    assert win_notify.available() is False


@_off_windows_only
@pytest.mark.asyncio
async def test_a_notification_that_cannot_be_posted_reports_false_not_raises():
    """A fallback that raises would break the announcement it stands in
    for. False means 'nobody was told', which is true."""
    assert await win_notify.notify("t", "m", subtitle="s") is False


# --- the token: parsing is the part a real box has to confirm --------------

# MEASURED on a real Windows 11 box (2026-09-08), no longer quoted from
# documentation. The shapes the Mac guessed were right; one detail was not,
# and it is kept below because it is the one a future edit could get wrong.
_WHOAMI_SAMPLE = '"desktop-abc\\ken","S-1-5-21-1111111111-2222222222-3333333333-1001"\n'

_ICACLS_OURS = (
    "C:\\data\\jarvis\\tool-token DESKTOP-ABC\\ken:(F)\n"
    "\n"
    "Successfully processed 1 files; Failed processing 0 files\n")

# The correction: real inherited ACEs carry an (I) flag before the rights,
# which the documentation sample omitted. `_parse_aces` splits on the LAST
# colon-paren group and was unaffected — measured, it returned the same three
# names from the real output — but a sample that cannot occur is a sample
# that stops testing the thing it names, so this is the real text.
_ICACLS_INHERITED = (
    "C:\\data\\jarvis\\tool-token NT AUTHORITY\\SYSTEM:(I)(F)\n"
    "                            BUILTIN\\Administrators:(I)(F)\n"
    "                            DESKTOP-ABC\\ken:(I)(F)\n"
    "\n"
    "Successfully processed 1 files; Failed processing 0 files\n")


def test_whoami_parsing_yields_the_account_and_its_sid():
    assert win_secrets._parse_whoami(_WHOAMI_SAMPLE) == (
        "desktop-abc\\ken",
        "S-1-5-21-1111111111-2222222222-3333333333-1001")


def test_whoami_parsing_refuses_anything_it_does_not_recognise():
    """None means "we do not know who we are", and the caller refuses
    rather than granting the file to a guess."""
    for junk in ("", "\n", "not csv at all", '"just-one-field"'):
        assert win_secrets._parse_whoami(junk) is None


def test_icacls_parsing_reads_one_ace_and_many():
    path = "C:\\data\\jarvis\\tool-token"
    assert win_secrets._parse_aces(_ICACLS_OURS, path) == ["desktop-abc\\ken"]
    assert win_secrets._parse_aces(_ICACLS_INHERITED, path) == [
        "nt authority\\system", "builtin\\administrators", "desktop-abc\\ken"]


def test_a_file_with_inherited_aces_is_not_ours(monkeypatch):
    """The ownership test. Windows has no cheap stdlib `getuid`, so what
    is checked instead is stronger for this purpose: a DACL that is not
    exactly what we would have written means we did not write it, and
    adopting it would mean trusting a token somebody else chose and knows."""
    monkeypatch.setattr(win_secrets, "_identity",
                        ("desktop-abc\\ken", "S-1-5-21-1"))
    monkeypatch.setattr(win_secrets, "_run",
                        lambda *a: (0, _ICACLS_INHERITED))
    assert win_secrets._granted_only_to_us("C:\\data\\jarvis\\tool-token") is False

    monkeypatch.setattr(win_secrets, "_run", lambda *a: (0, _ICACLS_OURS))
    assert win_secrets._granted_only_to_us("C:\\data\\jarvis\\tool-token") is True


def test_the_lockdown_breaks_inheritance_and_grants_by_sid(monkeypatch):
    """`/inheritance:r` REMOVES the inherited ACEs; `:e` would copy
    Administrators and SYSTEM in as explicit ones, which is the opposite of
    what is wanted. The grant names a SID because a domain account's name
    is ambiguous and its SID is not."""
    seen = {}
    monkeypatch.setattr(win_secrets, "_identity", ("desktop-abc\\ken", "S-1-5-21-9"))
    monkeypatch.setattr(win_secrets, "_run",
                        lambda *a: (seen.update(argv=list(a)), (0, ""))[1])
    win_secrets._lock_down("C:\\x\\tool-token")
    assert seen["argv"] == ["icacls", "C:\\x\\tool-token", "/inheritance:r",
                            "/grant:r", "*S-1-5-21-9:F"]


def test_a_token_that_cannot_be_locked_down_is_deleted_not_left(monkeypatch, tmp_path):
    """The failure this module exists to prevent: a token sitting at
    inherited permissions while every docstring promises otherwise."""
    path = tmp_path / "tool-token"
    monkeypatch.setattr(win_secrets, "_identity", ("desktop-abc\\ken", "S-1-5-21-9"))
    monkeypatch.setattr(win_secrets, "_run", lambda *a: (1, "access denied"))

    with pytest.raises(PrivateFileUnsupported):
        win_secrets.create_private(path)
    assert not path.exists(), "an unprotected token was left on disk"


def test_an_unknown_sid_refuses_rather_than_granting_to_a_guess(monkeypatch):
    monkeypatch.setattr(win_secrets, "_identity", None)
    monkeypatch.setattr(win_secrets, "_run", lambda *a: (1, "whoami is missing"))
    with pytest.raises(PrivateFileUnsupported):
        win_secrets._current_identity()


# --- the protocol still refuses where nothing is built ---------------------

def test_a_host_with_no_secrets_refuses_loudly():
    """The failure to avoid is a silent fallback that leaves the token
    readable while the docstring still promises otherwise."""
    host = jp.Host(name="plan9", capabilities=frozenset())
    for call in (lambda: host.secrets.create_private("/tmp/x"),
                 lambda: host.secrets.adopt_private("/tmp/x")):
        with pytest.raises(PrivateFileUnsupported):
            call()


def test_the_macos_secrets_still_keep_their_own_promise(tmp_path):
    """The POSIX implementation moved into the platform layer verbatim.
    This is the same guarantee, asserted from its new home."""
    if os.name == "nt":
        pytest.skip("POSIX semantics")
    from jarvis_platform.macos import secrets as mac_secrets
    path = tmp_path / "tool-token"
    fd = mac_secrets.create_private(path)
    assert fd is not None
    os.close(fd)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert mac_secrets.create_private(path) is None
