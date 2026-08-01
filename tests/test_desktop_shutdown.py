from __future__ import annotations

from types import SimpleNamespace

from offline_companion.shell.ui_host.desktop.app import _shutdown_runtime


class _StoppableBackend:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _ClosableConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_shutdown_runtime_stops_backend_before_forced_exit() -> None:
    backend = _StoppableBackend()
    connection = _ClosableConnection()
    bundle = SimpleNamespace(
        orchestrator=SimpleNamespace(backend=backend),
        conn=connection,
    )

    _shutdown_runtime(bundle)

    assert backend.stopped
    assert connection.closed


def test_shutdown_runtime_accepts_backends_without_stop() -> None:
    connection = _ClosableConnection()
    bundle = SimpleNamespace(
        orchestrator=SimpleNamespace(backend=object()),
        conn=connection,
    )

    _shutdown_runtime(bundle)

    assert connection.closed
