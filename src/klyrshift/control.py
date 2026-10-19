"""A local control socket for the running daemon.

Some state lives only in the daemon's memory, by design: the learned words and
the suppressed words are never written to disk (see ``learning.py`` and
``OFFLINE_AND_PRIVACY.md``). A one-shot CLI process therefore cannot read or
edit them by touching a file — it has to ask the daemon. This module is that
channel: a ``AF_UNIX`` socket the daemon listens on and the CLI connects to.

Design rules, all load-bearing:

* **Local only.** An ``AF_UNIX`` socket in the user's own runtime directory,
  with mode ``0600``. It is never a TCP socket, so it is not reachable from the
  network.
* **Same user only.** The socket is created under ``$XDG_RUNTIME_DIR`` (or the
  cache directory), which is already user-private; the ``0600`` mode and an
  owner check make a second line of defence.
* **No typed text on disk.** A request carries a *word the user chose to
  promote or forget*, the same data ``dict add`` already stores deliberately. It
  is never logged and never written to the learning profile.
* **Bounded.** A one-line JSON request and a one-line JSON response, each capped
  at a small size, with a short timeout, so a stuck client cannot block the
  daemon's event loop.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from .config import cache_dir

logger = logging.getLogger(__name__)

SOCKET_FILE_NAME: Final[str] = "control.sock"
# A request is one small JSON object; anything larger is not one of ours.
MAX_REQUEST_BYTES: Final[int] = 64 * 1024
# How long the client waits for the daemon's reply.
CLIENT_TIMEOUT: Final[float] = 2.0
# How long the daemon will wait for a client to finish sending its request. This
# runs on the event-loop thread, so it must stay short: a client that connects
# and then sends nothing would otherwise freeze every keystroke for that long.
REQUEST_READ_TIMEOUT: Final[float] = 0.25

# The request handler: given a decoded request, return a response mapping.
Handler = Callable[[dict[str, Any]], dict[str, Any]]


def socket_path() -> Path:
    """Return the control-socket path.

    ``$XDG_RUNTIME_DIR`` is preferred (it is already ``0700`` and cleared at
    logout); the cache directory is the fallback for a session without one.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "klyrshift" / SOCKET_FILE_NAME
    return cache_dir() / SOCKET_FILE_NAME


def _request(payload: dict[str, Any], *, timeout: float = CLIENT_TIMEOUT) -> dict[str, Any] | None:
    """Send one request to the daemon and return its response.

    Returns ``None`` when no daemon is listening, the socket is not ours, or the
    exchange fails — the caller treats that as "the daemon is not running" rather
    than an error, because a missing socket is the normal state.
    """
    path = socket_path()
    if not path.exists():
        return None
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        buffer = b""
        while b"\n" not in buffer and len(buffer) <= MAX_REQUEST_BYTES:
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer += chunk
    except OSError:
        logger.debug("Control socket request failed", exc_info=True)
        return None
    finally:
        client.close()
    line, _, _ = buffer.partition(b"\n")
    if not line:
        return None
    try:
        response: object = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return response if isinstance(response, dict) else None


# --- client API -----------------------------------------------------------


def learn_list() -> list[str] | None:
    """Return the daemon's learned words, or ``None`` when it is not running."""
    response = _request({"cmd": "learn.list"})
    if response is None:
        return None
    words = response.get("words")
    if not isinstance(words, list):
        return None
    return [str(w) for w in words]


def learn_promote(word: str) -> bool | None:
    """Ask the daemon to promote ``word``; ``None`` when it is not running."""
    response = _request({"cmd": "learn.promote", "word": word})
    if response is None:
        return None
    return bool(response.get("ok"))


def learn_forget(word: str) -> bool | None:
    """Ask the daemon to forget ``word``; ``None`` when it is not running."""
    response = _request({"cmd": "learn.forget", "word": word})
    if response is None:
        return None
    return bool(response.get("ok"))


class ControlServer:
    """The daemon side of the control socket.

    The listening socket is non-blocking and is registered with the daemon's
    selector. :meth:`handle` accepts one connection, reads one request, calls the
    handler and writes the response. Everything is best-effort: a malformed
    request gets an ``{"error": ...}`` reply, and a broken connection is dropped
    without disturbing the event loop.
    """

    def __init__(self, handler: Handler, path: Path | None = None) -> None:
        self._handler = handler
        self.path = path or socket_path()
        self._socket: socket.socket | None = None

    def start(self) -> bool:
        """Bind and listen. Returns ``False`` when the socket cannot be created."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self._owned_by_us():
                logger.warning(
                    "Refusing the control socket: %s is not owned by us", self.path.parent
                )
                return False
            # A leftover socket from a crashed daemon would make ``bind`` fail;
            # the lock file already guarantees only one daemon runs, so removing
            # it here is safe.
            self.path.unlink(missing_ok=True)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(self.path))
            # Owner-only, before anyone else can connect.
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            server.listen(4)
            server.setblocking(False)
        except OSError:
            logger.warning("Could not create the control socket %s", self.path, exc_info=True)
            return False
        self._socket = server
        logger.info("Control socket listening at %s", self.path)
        return True

    @property
    def fileno(self) -> int:
        """Return the listening socket's file descriptor."""
        if self._socket is None:
            raise RuntimeError("control server is not started")
        return self._socket.fileno()

    def handle(self) -> None:
        """Accept and serve every pending connection (non-blocking).

        The *accept* is non-blocking, but each connection is then read with a
        short timeout: the client is a local CLI that sends its request in one
        write, so a slow or silent connection is dropped quickly rather than
        stalling the daemon's event loop.
        """
        if self._socket is None:
            return
        while True:
            try:
                connection, _address = self._socket.accept()
            except BlockingIOError:
                return
            except OSError:
                return
            try:
                self._serve(connection)
            finally:
                connection.close()

    def _serve(self, connection: socket.socket) -> None:
        """Read one request from ``connection`` and write one response."""
        connection.settimeout(REQUEST_READ_TIMEOUT)
        buffer = b""
        try:
            while b"\n" not in buffer and len(buffer) <= MAX_REQUEST_BYTES:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                buffer += chunk
        except OSError:
            return
        line, _, _ = buffer.partition(b"\n")
        if not line:
            return
        response = self._dispatch(line)
        try:
            connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
        except OSError:
            logger.debug("Could not write the control response", exc_info=True)

    def _dispatch(self, raw: bytes) -> dict[str, Any]:
        """Decode ``raw``, run the handler, and turn failures into a reply."""
        try:
            request: object = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"error": "malformed request"}
        if not isinstance(request, dict):
            return {"error": "malformed request"}
        try:
            return self._handler(request)
        except Exception:  # pragma: no cover - defensive: never break the loop
            logger.debug("Control handler raised", exc_info=True)
            return {"error": "internal error"}

    def _owned_by_us(self) -> bool:
        """Return whether the parent directory is owned by this user.

        The socket file is created by :meth:`start`, so it is ours by
        construction; the directory it lives in is what an attacker could have
        planted. Checking it is the check that has teeth.
        """
        try:
            return self.path.parent.stat().st_uid == os.getuid()
        except OSError:
            logger.warning("Could not stat %s", self.path.parent, exc_info=True)
            return False

    def stop(self) -> None:
        """Close the socket and remove its file."""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                logger.debug("Could not close the control socket", exc_info=True)
            self._socket = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Could not remove the control socket file", exc_info=True)
