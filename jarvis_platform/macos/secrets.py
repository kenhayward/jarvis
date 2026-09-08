"""Files only their owner may read, the POSIX way.

Moved verbatim out of `data_paths.py`, where it was two functions inlined
mid-file. The behaviour is unchanged; what is new is that it now sits
opposite a second implementation, so the promise it keeps had to be written
down as a protocol first — see `jarvis_platform.base.Secrets`.
"""

from __future__ import annotations

import os
import stat as _stat
from pathlib import Path


def create_private(path: Path) -> int | None:
    """A new file only its owner can read, or None if one already exists.

    O_EXCL at mode 0600 directly — never briefly world-readable at umask
    permissions between the write and a chmod.
    """
    try:
        return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None


def adopt_private(path: Path) -> int:
    """An existing file, opened and proven ours, forced back to 0600.

    Adopted through ONE file descriptor: opened O_NOFOLLOW, checked with
    fstat, chmodded with fchmod, and read with that same fd. An earlier
    version did `path.chmod(); path.read_text()`, two lookups of a name an
    attacker could change in between — and both followed symlinks, so a link
    planted at this path meant any file the user owns could be forced to
    0600, and the token JARVIS then trusted was one somebody else wrote.

    A path that is not a regular file this user owns raises, rather than
    being quietly replaced: it is somebody else's file, and deleting it is
    not ours to do.
    """
    fd = os.open(str(path), os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not _stat.S_ISREG(info.st_mode):
            raise OSError(f"{path} is not a regular file")
        if info.st_uid != os.getuid():
            raise OSError(f"{path} is owned by uid {info.st_uid}, not by us")
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


def restrict(path: Path) -> None:
    """An existing file, taken down to owner-only.

    Exactly the `chmod(0o600)` the caller used to do inline, so nothing
    about this platform changes; the point of routing it through the
    protocol is that Windows cannot express the same promise that way.
    """
    os.chmod(str(path), 0o600)
