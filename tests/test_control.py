"""Tests for :mod:`klyrshift.control` and the daemon's control handler."""

from __future__ import annotations

import json
import os
import selectors
import socket
import stat
import threading
from pathlib import Path

import pytest

from klyrshift import control


@pytest.fixture
def runtime_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the control socket at a private temporary runtime directory."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    return tmp_path / "runtime"


class _ServerThread:
    """Run a :class:`control.ControlServer` on a background thread."""

    def __init__(self, handler: control.Handler) -> None:
        self.server = control.ControlServer(handler)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._selector: selectors.BaseSelector | None = None

    def __enter__(self) -> control.ControlServer:
        assert self.server.start()
        self._selector = selectors.DefaultSelector()
        self._selector.register(self.server.fileno, selectors.EVENT_READ, self.server)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self.server

    def _serve(self) -> None:
        assert self._selector is not None
        while not self._stop.is_set():
            for key, _mask in self._selector.select(0.05):
                key.data.handle()

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._selector is not None:
            self._selector.close()
        self.server.stop()


def test_socket_is_private_and_local(runtime_dir: Path) -> None:
    """The socket is an owner-only AF_UNIX socket, never a network port."""
    with _ServerThread(lambda _req: {"ok": True}) as server:
        assert server.path.is_socket()
        mode = stat.S_IMODE(server.path.stat().st_mode)
        assert mode == 0o600
    # Stopping removes the file, so a stale socket never blocks the next start.
    assert not server.path.exists()


def _words_handler(words: list[str]) -> control.Handler:
    """A handler that serves ``learn.list`` from ``words`` and accepts edits."""

    def handler(request: dict[str, object]) -> dict[str, object]:
        command = request.get("cmd")
        if command == "learn.list":
            return {"words": list(words)}
        word = request.get("word")
        if isinstance(word, str):
            words.append(word)
        return {"ok": True}

    return handler


def test_request_round_trip(runtime_dir: Path) -> None:
    """A request reaches the handler and its response comes back."""
    seen: list[dict[str, object]] = []

    def handler(request: dict[str, object]) -> dict[str, object]:
        seen.append(request)
        return {"words": ["ok"]}

    with _ServerThread(handler):
        assert control.learn_list() == ["ok"]
    assert seen == [{"cmd": "learn.list"}]


def test_learn_list_promote_forget(runtime_dir: Path) -> None:
    """The three client calls drive a stateful handler end to end."""
    words: list[str] = ["привет"]

    def handler(request: dict[str, object]) -> dict[str, object]:
        command = request.get("cmd")
        if command == "learn.list":
            return {"words": list(words)}
        word = request.get("word")
        assert isinstance(word, str)
        if command == "learn.promote":
            words.append(word)
            return {"ok": True}
        if command == "learn.forget":
            words.remove(word)
            return {"ok": True}
        return {"error": "unknown"}

    with _ServerThread(handler):
        assert control.learn_list() == ["привет"]
        assert control.learn_promote("мир") is True
        assert control.learn_list() == ["привет", "мир"]
        assert control.learn_forget("привет") is True
        assert control.learn_list() == ["мир"]


def test_client_returns_none_without_a_daemon(runtime_dir: Path) -> None:
    """No socket means "no daemon", not an exception."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    assert control.learn_list() is None
    assert control.learn_promote("x") is None
    assert control.learn_forget("x") is None


def test_malformed_request_gets_an_error_not_a_crash(runtime_dir: Path) -> None:
    """Garbage on the socket yields ``{"error": ...}`` and the server survives."""
    with _ServerThread(_words_handler([])) as server:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(server.path))
        client.sendall(b"not json\n")
        reply = client.recv(4096)
        client.close()
        assert json.loads(reply.decode()) == {"error": "malformed request"}
        # The server is still alive for the next, well-formed request.
        assert control.learn_list() == []


def test_oversized_request_is_bounded(runtime_dir: Path) -> None:
    """A request larger than the cap is rejected, not buffered forever."""
    with _ServerThread(_words_handler([])) as server:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(server.path))
        client.sendall(b"x" * (control.MAX_REQUEST_BYTES + 10))
        client.close()
        # No assertion on the reply: the point is that the server did not hang.
        assert control.learn_list() == []


def test_handler_exception_is_contained(runtime_dir: Path) -> None:
    """A handler that raises yields an error reply, never a broken loop."""

    def handler(_request: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    with _ServerThread(handler):
        assert control.learn_list() is None


def test_silent_client_does_not_stall_the_server(runtime_dir: Path) -> None:
    """A client that connects and sends nothing is dropped quickly.

    ``handle`` runs on the daemon's event-loop thread, so this must return in
    well under the client timeout; otherwise a stray connection would freeze
    typing. The server is driven directly here (no background thread) so the
    silent client is definitely the one under test.
    """
    import time

    server = control.ControlServer(_words_handler([]))
    assert server.start()
    try:
        silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        silent.connect(str(server.path))
        try:
            start = time.monotonic()
            server.handle()
            elapsed = time.monotonic() - start
        finally:
            silent.close()
        assert elapsed < control.CLIENT_TIMEOUT
        # The server still serves a real request afterwards (driven by hand, so
        # no second thread is needed).
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(server.path))
        client.sendall(b'{"cmd": "learn.list"}\n')
        server.handle()
        reply = json.loads(client.recv(4096).decode())
        client.close()
        assert reply == {"words": []}
    finally:
        server.stop()


def test_server_refuses_a_foreign_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A socket directory we do not own is refused, not served on."""
    target = tmp_path / "klyrshift" / "control.sock"
    server = control.ControlServer(lambda _req: {}, path=target)
    monkeypatch.setattr(server, "_owned_by_us", lambda: False)
    assert server.start() is False
    assert not target.exists()


def test_socket_path_uses_cache_dir_without_runtime_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without ``XDG_RUNTIME_DIR`` the socket falls back to the cache dir."""
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    path = control.socket_path()
    assert path.name == control.SOCKET_FILE_NAME
    assert str(tmp_path / "cache") in str(path)


def test_daemon_loop_serves_the_control_socket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A running daemon loop answers a real control-socket request.

    This is the integration the whole feature rests on: the socket is registered
    with the same selector as the keyboards, and a request is served on the loop
    thread. A fake device keeps the loop alive without touching real hardware.
    """
    import selectors
    import threading
    import time

    pytest.importorskip("evdev")
    from klyrshift.config import Config
    from klyrshift.daemon import KlyrshiftDaemon
    from klyrshift.detector import LanguageDetector

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

    class FakeDevice:
        def __init__(self) -> None:
            self.fd = -1

        def read(self) -> list[object]:
            time.sleep(0.02)
            return []

        def close(self) -> None:
            return None

    class Switcher:
        backend = "fake"

        def get_current_layout(self, *, force: bool = False) -> str:
            return "us"

        def switch_to(self, layout: str) -> bool:
            return True

    class Injector:
        backend = "fake"

        def can_type(self, char: str, layout: str) -> bool:
            return False

    config = Config(analysis_timeout=0.8, stop_words=[])
    detector = LanguageDetector(converter=None, stop_words=[], min_word_length=3)
    daemon = KlyrshiftDaemon(config, detector=detector, switcher=Switcher(), injector=Injector())
    daemon._running = True

    # A self-pipe stands in for a keyboard: it is a real fd the selector can
    # poll, so the loop behaves exactly as it does with an evdev device.
    read_fd, write_fd = os.pipe()
    selector = selectors.DefaultSelector()
    selector.register(read_fd, selectors.EVENT_READ, FakeDevice())
    daemon._start_control()
    assert daemon._control is not None
    selector.register(daemon._control.fileno, selectors.EVENT_READ, daemon._control)

    thread = threading.Thread(target=daemon._loop, args=(selector,), daemon=True)
    thread.start()
    try:
        # The daemon starts with an empty vocabulary.
        deadline = time.time() + 5
        words = None
        while time.time() < deadline:
            words = control.learn_list()
            if words is not None:
                break
            time.sleep(0.05)
        assert words == []

        assert control.learn_promote("vercel") is True
        deadline = time.time() + 5
        while time.time() < deadline:
            if control.learn_list() == ["vercel"]:
                break
            time.sleep(0.05)
        assert control.learn_list() == ["vercel"]

        assert control.learn_forget("vercel") is True
        deadline = time.time() + 5
        while time.time() < deadline:
            if control.learn_list() == []:
                break
            time.sleep(0.05)
        assert control.learn_list() == []
    finally:
        daemon.stop()
        thread.join(timeout=5)
        selector.close()
        daemon._stop_control()
        os.close(read_fd)
        os.close(write_fd)

    # Shutting down removes the socket file.
    assert not control.socket_path().exists()
