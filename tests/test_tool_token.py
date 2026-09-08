"""The loopback tool token, which admits its bearer to every acting tool.

There were no tests on this before the platform seam was extracted from it,
which is a poor state for the file that gates `/internal/tool`. These pin
the promise itself — created private, adopted only when proven private —
so a second platform implementation has something to be held to.
"""

import os
import stat

import pytest

import data_paths


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_a_new_token_is_created_readable_only_by_its_owner():
    token = data_paths.ensure_tool_token()
    path = data_paths.tool_token_path()
    assert token and path.read_text(encoding="utf-8").strip() == token
    if os.name != "nt":
        assert _mode(path) == 0o600, oct(_mode(path))


def test_the_same_token_is_adopted_across_calls():
    """It has to survive a restart — the MCP child holds the previous one."""
    first = data_paths.ensure_tool_token()
    assert data_paths.ensure_tool_token() == first


@pytest.mark.skipif(os.name == "nt", reason="POSIX adopt-and-tighten; Windows "
                                            "refuses a foreign file instead")
def test_a_pre_existing_loose_file_has_its_mode_forced_back():
    """POSIX can see the file is this user's and simply tighten it.

    Windows cannot: with no cheap `getuid` it uses the DACL as the ownership
    test, an inherited one proves nothing, and it therefore REFUSES rather
    than re-permissioning. That half is asserted by
    `test_a_pre_existing_token_windows_cannot_prove_is_ours_is_refused` in
    tests/test_internal_tool.py.
    """
    path = data_paths.tool_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("already-here")
    os.chmod(path, 0o644)

    assert data_paths.ensure_tool_token() == "already-here"
    assert _mode(path) == 0o600, oct(_mode(path))


def test_an_empty_file_is_filled_rather_than_trusted():
    """An empty token is not a token, whoever left it there.

    The planted file is made PRIVATE first, so it is one JARVIS could have
    written itself. Without that step Windows refuses it as somebody else's
    before the emptiness is ever considered — which is correct behaviour but
    a different property, and it would leave this one untested there. The
    question here is what happens to OUR own empty file.
    """
    import jarvis_platform
    path = data_paths.tool_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("   \n", encoding="utf-8")
    jarvis_platform.current().secrets.restrict(path)

    token = data_paths.ensure_tool_token()
    assert token.strip() == token and len(token) > 20
    assert path.read_text(encoding="utf-8").strip() == token


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_a_symlink_planted_at_the_path_is_refused(tmp_path):
    """O_NOFOLLOW is the whole point of the adopt path.

    Without it, a link planted here means two things at once: any file the
    user owns can be forced to 0600, and the token JARVIS then trusts is one
    somebody else wrote.
    """
    path = data_paths.tool_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    victim = tmp_path / "somebody-elses-secret"
    victim.write_text("not-a-token")
    path.symlink_to(victim)

    with pytest.raises(OSError):
        data_paths.ensure_tool_token()
    assert victim.read_text(encoding="utf-8") == "not-a-token"


@pytest.mark.skipif(os.name == "nt", reason="POSIX fifo")
def test_something_that_is_not_a_regular_file_is_refused():
    """Refused rather than replaced: it is somebody else's file, and
    deleting it is not ours to do."""
    path = data_paths.tool_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(str(path))

    with pytest.raises(OSError, match="not a regular file"):
        data_paths.ensure_tool_token()
    assert path.is_fifo()


def test_the_unsupported_platform_error_is_not_an_oserror():
    """`web_auth` denies on any exception and startup refuses to boot, so
    both already fail closed. This keeps it out of reach of code that is
    handling ordinary file trouble with `except OSError`."""
    assert issubclass(data_paths.PrivateFileUnsupported, RuntimeError)
    assert not issubclass(data_paths.PrivateFileUnsupported, OSError)
