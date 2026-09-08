"""Files only their owner may read, the Windows way.

**Written from documentation, not from measurement.** Everything else in
this repository is measured on the machine it runs on; this could not be,
because it was written on a Mac. The two things that could be wrong are
isolated so a real Windows box can correct them in one place each:
`_parse_aces` (what `icacls` prints) and `_parse_whoami` (what
`whoami /user /fo csv /nh` prints). `tests/test_windows_secrets.py` pins
both against sample output — replace the samples with real ones and the
tests will say whether anything else has to move.

POSIX states the requirement as "mode 0600, and do not follow symlinks".
Neither half survives translation: `O_NOFOLLOW`, `getuid` and `fchmod` do
not exist here. Windows says the same thing as a DACL, so the requirement
becomes "break inheritance, then grant exactly one principal".

`icacls` rather than pywin32, per CLAUDE.md's rule that a dependency has to
earn its place: this needs two commands at boot and nothing else, `icacls`
and `whoami` have shipped with Windows since Vista, and a package that
exists only on one platform would have to be conditional in
`requirements.txt` for a saving of about forty lines.

Three things are load-bearing and should survive any rewrite:

1. **The identity of what we opened is confirmed.** Windows has no
   `O_NOFOLLOW`, so the file is `lstat`-ed first (which does not follow),
   rejected if it is a reparse point — that covers symlinks AND directory
   junctions — then opened, and the open descriptor's `(st_dev, st_ino)` is
   compared with the `lstat`'s. If they differ, something was swapped
   between the two calls and we refuse. That is the closest Windows gets to
   the single-descriptor discipline the POSIX side uses.

2. **Adoption requires the DACL we would have written.** Not an owner
   check — Windows has no cheap standard-library equivalent of `getuid` —
   but something stronger for this purpose: a file whose DACL is not
   exactly one ACE granting this user full control is a file we did not
   create, so it is refused rather than adopted. Adopting somebody else's
   file would mean trusting a token they chose and know.

3. **A file we cannot lock down is deleted, not left.** If `icacls` fails
   after `create_private` has made the file, the file is removed before the
   error propagates. A token sitting at inherited permissions is precisely
   what this module exists to prevent.
"""

from __future__ import annotations

import logging
import os
import stat as _stat
import subprocess
from pathlib import Path

from ..base import PrivateFileUnsupported

log = logging.getLogger("jarvis.platform.secrets")

# Both commands are local and answer in milliseconds. This runs at boot with
# the server waiting on it, so a wedged one must not hang startup.
_COMMAND_TIMEOUT = 10.0

# Set by `icacls` on a reparse point, among others. Any non-zero tag means
# the path is not the plain file it appears to be.
_NOT_A_REPARSE_POINT = 0


def _run(*argv: str) -> tuple[int, str]:
    """One command, bounded. Never raises; returns (rc, combined output).

    The single subprocess seam in this module, so tests mock one thing —
    the pattern `screen._run` and `tts._spawn_synth` already use.
    """
    try:
        out = subprocess.run(list(argv), capture_output=True, text=True,
                             timeout=_COMMAND_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return -1, f"failed to run {argv[0]}: {e}"
    return out.returncode, (out.stdout or "") + (out.stderr or "")


def _parse_whoami(output: str) -> tuple[str, str] | None:
    """(account, sid) out of `whoami /user /fo csv /nh`, or None.

    Documented output is one CSV line:

        "desktop-abc\\ken","S-1-5-21-1111111111-2222222222-3333333333-1001"

    The account name is kept for comparing against what `icacls` prints
    (which resolves SIDs to names), and the SID for granting, because a
    domain account's name is ambiguous and its SID is not.
    """
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) != 2:
            parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) == 2 and parts[1].upper().startswith("S-1-"):
            return parts[0], parts[1]
    return None


def _parse_aces(output: str, path: str) -> list[str] | None:
    """The principals in an `icacls <path>` listing, or None if unreadable.

    Documented output, with the path only on the first line:

        C:\\x\\tool-token NT AUTHORITY\\SYSTEM:(F)
                          BUILTIN\\Administrators:(F)
                          DESKTOP-ABC\\ken:(F)

        Successfully processed 1 files; Failed processing 0 files

    Returns the principal of each ACE, lower-cased. The permission mask is
    deliberately not parsed: this module only ever asks "is this exactly
    one principal, and is it us", and a mask that grants us less than we
    asked for would have failed at the `icacls /grant` step.
    """
    principals: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            break                      # the blank line ends the ACE list
        if line.lower().startswith("successfully processed"):
            break
        if line.startswith(path):
            line = line[len(path):].strip()
            if not line:
                continue               # a path on a line of its own
        principal, sep, _mask = line.rpartition(":")
        if not sep or not principal:
            return None                # not a shape we recognise; refuse
        principals.append(principal.strip().lower())
    return principals or None


_identity: tuple[str, str] | None = None


def _current_identity() -> tuple[str, str]:
    """(account, sid) for this process's user. Cached; raises if unknown.

    Refusing is correct here: without knowing who we are there is no
    principal to grant to, and guessing would produce a file granted to
    somebody.
    """
    global _identity
    if _identity is None:
        rc, out = _run("whoami", "/user", "/fo", "csv", "/nh")
        parsed = _parse_whoami(out) if rc == 0 else None
        if parsed is None:
            raise PrivateFileUnsupported(
                f"could not determine this Windows user's SID: {out.strip()[:200]}")
        _identity = parsed
    return _identity


def _lock_down(path: Path) -> None:
    """Break inheritance and grant exactly this user. Raises on failure.

    `/inheritance:r` removes the inherited ACEs rather than converting them
    to explicit ones — `:e` would copy Administrators and SYSTEM in, which
    is the opposite of what is wanted. `/grant:r` REPLACES any existing
    grant for the principal instead of adding to it.

    The SID form (`*S-1-...`) rather than the name: a domain account's name
    depends on how it is spelled and its SID does not.
    """
    _account, sid = _current_identity()
    rc, out = _run("icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F")
    if rc != 0:
        raise PrivateFileUnsupported(
            f"could not restrict {path} to this user: {out.strip()[:200]}")


def _granted_only_to_us(path: Path) -> bool:
    """Whether this file's DACL is exactly one ACE, granting this user."""
    account, _sid = _current_identity()
    rc, out = _run("icacls", str(path))
    if rc != 0:
        return False
    principals = _parse_aces(out, str(path))
    return principals == [account.lower()]


def create_private(path: Path) -> int | None:
    """A new file only this user can read, or None if one already exists."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                     | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        return None
    try:
        _lock_down(path)
    except BaseException:
        # A token we could not lock down must not survive this call. It
        # would sit at inherited permissions while every docstring above
        # promises otherwise, which is the failure mode this module exists
        # to prevent.
        os.close(fd)
        try:
            os.unlink(str(path))
        except OSError as e:                       # pragma: no cover
            log.error("could not remove the unprotected token at %s: %s", path, e)
        raise
    return fd


def adopt_private(path: Path) -> int:
    """An existing file, proven ours, opened for reading.

    See the module docstring for why identity is confirmed across the
    lstat/open pair and why the DACL is the ownership test.
    """
    before = os.lstat(str(path))
    if not _stat.S_ISREG(before.st_mode):
        raise OSError(f"{path} is not a regular file")
    if getattr(before, "st_reparse_tag", _NOT_A_REPARSE_POINT) != _NOT_A_REPARSE_POINT:
        raise OSError(f"{path} is a reparse point, not a plain file")

    if not _granted_only_to_us(path):
        # Refused, never adopted and never re-permissioned: adopting it
        # would mean trusting a token somebody else chose and knows, and
        # deleting somebody else's file is not ours to do.
        raise OSError(f"{path} is not granted solely to this user; "
                      f"remove it if it is yours and JARVIS will make a new one")

    fd = os.open(str(path), os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise OSError(f"{path} changed between the check and the open")
    except BaseException:
        os.close(fd)
        raise
    return fd
