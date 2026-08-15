from __future__ import annotations

import threading
from types import SimpleNamespace

from offline_companion.shell.ui_host.desktop.app import (
    _DeferredTimerRegistry,
    _shutdown_runtime,
)


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


def test_deferred_timer_registry_cancels_daemon_timer() -> None:
    registry = _DeferredTimerRegistry()
    callback_called = threading.Event()

    timer = registry.schedule(1.0, callback_called.set)
    registry.cancel_all()
    timer.join(timeout=0.5)

    assert timer.daemon
    assert not timer.is_alive()
    assert not callback_called.is_set()
