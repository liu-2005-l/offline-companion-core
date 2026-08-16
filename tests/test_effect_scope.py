"""EffectScope 资源回滚与释放测试。"""

import asyncio

import pytest

from offline_companion.core.lifecycle import EffectScope


def test_add_collects_disposer_and_dispose_is_lifo_and_idempotent() -> None:
    order: list[str] = []
    scope = EffectScope("test")
    scope.add(lambda: order.append("setup-1") or (lambda: order.append("dispose-1")))
    scope.add(lambda: order.append("setup-2") or (lambda: order.append("dispose-2")))

    asyncio.run(scope.dispose())
    asyncio.run(scope.dispose())

    assert order == ["setup-1", "setup-2", "dispose-2", "dispose-1"]
    assert scope.is_disposed is True


def test_setup_failure_rolls_back_registered_effects() -> None:
    disposed: list[str] = []
    scope = EffectScope("rollback")
    scope.add(lambda: lambda: disposed.append("first"))

    with pytest.raises(RuntimeError, match="boom"):
        scope.add(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert disposed == ["first"]


def test_disposer_failure_does_not_block_other_disposers(caplog) -> None:
    disposed: list[str] = []
    scope = EffectScope("failure")
    scope.add_disposer(lambda: disposed.append("first"))
    scope.add_disposer(lambda: (_ for _ in ()).throw(RuntimeError("bad disposer")))

    asyncio.run(scope.dispose())

    assert disposed == ["first"]
    assert "Disposer failed in failure" in caplog.text


def test_add_disposer_and_add_after_dispose() -> None:
    disposed: list[str] = []
    scope = EffectScope("direct")
    scope.add_disposer(lambda: disposed.append("direct"))
    asyncio.run(scope.dispose())

    with pytest.raises(RuntimeError, match="already disposed"):
        scope.add_disposer(lambda: None)
    with pytest.raises(RuntimeError, match="already disposed"):
        scope.add(lambda: None)
    assert disposed == ["direct"]


def test_async_disposer_is_awaited() -> None:
    disposed: list[str] = []
    scope = EffectScope("async")

    async def disposer() -> None:
        await asyncio.sleep(0)
        disposed.append("async")

    scope.add_disposer(disposer)
    asyncio.run(scope.dispose())

    assert disposed == ["async"]
