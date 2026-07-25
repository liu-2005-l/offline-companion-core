"""测试：B 层计算依赖白名单。"""

from __future__ import annotations

from scripts.ci import check_imports


def test_b_layer_compute_deps_are_explicitly_whitelisted() -> None:
    """onnxruntime 与 tokenizers 应作为 B 层计算依赖显式登记。"""
    assert "onnxruntime" in check_imports.B_LAYER_COMPUTE_DEPS
    assert "tokenizers" in check_imports.B_LAYER_COMPUTE_DEPS
