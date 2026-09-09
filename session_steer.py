"""Post a message into a running Claude Code session.

The wire format is one JSON line on the session's inbox. It carries PEER
authority, not the user's: the session receives it as a new turn (or queues it
between tool calls if busy), but it cannot dismiss a permission prompt or a
modal dialog. On this machine those are the two `waitingFor` reasons that
actually occur, so the caller must check before promising a fix.

THE INBOX IS NOT THE SAME OBJECT ON EVERY PLATFORM, and the payload above it
is. POSIX gets an AF_UNIX socket; Windows gets a NAMED PIPE, because
`socket.AF_UNIX` is not exposed by CPython there at all — the roster simply
publishes `\\\\.\\pipe\\LOCAL\\cc-msg-<hex>` in the same `messagingSocketPath`
field. So the two transports differ and nothing above them does: the same
JSON lines, the same optional auth line, the same four outcomes.

Which transport is chosen is decided by the VALUE, not by `sys.platform` —
the same reasoning as `session_watch.inbox_exists`. What needs the pipe
treatment is a pipe, and a path outside the pipe namespace is an ordinary
filesystem name whichever machine reads it.
"""

from __future__ import annotations

import json
import os
import socket

import session_watch

SENT = "sent"          # the bytes left over the socket — NOT that the target
                        # session accepted or even received them; no reply is
                        # ever read back to confirm that
NOT_LIVE = "not_live"
REFUSED = "refused"
FAILED = "failed"


def _post_over_pipe(pipe_path: str, payload: bytes) -> str:
    """The Windows half: one write to a named pipe, opened as a file.

    A pipe in the `\\\\.\\pipe\\` namespace is opened with the ordinary file
    API — no ctypes, no third-party package. Measured against a pipe server
    built for the test: the bytes arrive whole and in order.

    The outcomes map cleanly onto the same four the socket path returns.
    FileNotFoundError is a pipe that has gone, which is exactly the stale
    `.sock` case and so NOT_LIVE. Everything else is FAILED, and the one to
    know about is ERROR_PIPE_BUSY (231): the session is alive but every
    instance of its pipe is in use, so the message did not go — which is
    FAILED and not NOT_LIVE, because there IS something there to talk to.

    No timeout is taken because there is nothing here that waits on one.
    `open` does not block on a busy pipe, it fails at once with 231; and the
    payload is one short line, far inside the pipe's own buffer, so the
    write does not wait for the far side to read. The caller runs this on a
    worker thread in any case (`server._perform_staged_steers`), so a write
    that did stall would park that thread rather than the voice loop.
    """
    try:
        with open(pipe_path, "wb", buffering=0) as fh:
            fh.write(payload)
    except FileNotFoundError:
        return NOT_LIVE
    except OSError:
        return FAILED
    return SENT


def post_to_session(socket_path: str | None, prompt: str,
                    timeout: float = 5.0) -> str:
    """Deliver one prompt. Returns `sent`, `not_live`, `refused`, or `failed`.

    A missing socket file and a stale one left by a dead process are both
    `not_live`: from the user's point of view there is nothing to talk to.
    """
    if not prompt or not prompt.strip():
        return REFUSED
    # `session_watch.inbox_exists`, not `Path(...).exists()`. Against a named
    # pipe the latter OPENS an instance to stat it, so on a busy one it does
    # not answer False, it RAISES — measured, and the whole reason that
    # helper exists. One answer to "is this inbox there", shared by the
    # watcher that reports it and the sender that uses it.
    if not socket_path or not session_watch.inbox_exists(socket_path):
        return NOT_LIVE

    lines = []
    # What is actually known about this token, recorded so nobody "fixes" it
    # into something it cannot be: it is optional on macOS (the target may
    # require none at all); we can only ever send OUR OWN — there is no way
    # to look up another process's; tokens observably differ between
    # sessions (3 distinct values seen across 7 live sessions on one
    # machine, and a server started from a plain terminal has none). If the
    # target validates a token and ours does not match — or it has none and
    # we send one — the send below can fail silently from our side: a
    # successful `sendall` proves the bytes left this process, not that the
    # target accepted them. See the SENT docstring above and the wording at
    # the call site in server.py's `_perform_staged_steers`.
    token = os.getenv("CLAUDE_CODE_MESSAGING_TOKEN", "")
    if token:
        lines.append(json.dumps({"type": "auth", "token": token}))
    lines.append(json.dumps({"type": "user",
                             "message": {"role": "user", "content": prompt.strip()}}))
    payload = ("\n".join(lines) + "\n").encode()

    if session_watch.is_pipe(socket_path):
        return _post_over_pipe(socket_path, payload)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(socket_path)
    except (ConnectionRefusedError, FileNotFoundError):
        return NOT_LIVE           # a stale .sock from a process that has gone
    except OSError:
        return FAILED
    try:
        sock.sendall(payload)
    except OSError:
        return FAILED
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return SENT
