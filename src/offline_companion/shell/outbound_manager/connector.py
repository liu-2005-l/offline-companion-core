"""connector：出站 HTTP 客户端占位（A3；Phase 1 起可引入 httpx）。"""

from __future__ import annotations


def post_remote_inference_stub() -> None:
    """摘要：占位函数；未来在此文件内引入 httpx 并发起受控出站请求。

    说明：Phase 0 不执行任何网络 I/O；保持文件存在以满足架构白名单边界。
    """
    raise NotImplementedError("Remote inference connector not implemented in Phase 0.")
