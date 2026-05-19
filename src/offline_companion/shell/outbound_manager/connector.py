"""connector：出站 HTTP 客户端（A3；唯一允许使用 httpx 的模块）。"""

from __future__ import annotations

import json
import os
from typing import Any

from offline_companion.shared.errors import CloudConnectorError
from offline_companion.shared.types import CloudCompletionRequest, CloudCompletionResponse


def _use_cloud_stub() -> bool:
    return os.environ.get("OFFLINE_COMPANION_CLOUD_STUB", "").strip() in ("1", "true", "yes")


def post_cloud_completion(
    request: CloudCompletionRequest,
    *,
    url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
) -> CloudCompletionResponse:
    """摘要：向配置的云端端点发起最小补全请求。

    参数：
        request: 出站请求 DTO。
        url: API 地址；默认读 ``OFFLINE_COMPANION_CLOUD_URL``。
        api_key: 可选 Bearer；默认读 ``OFFLINE_COMPANION_CLOUD_API_KEY``。
        model: 模型名；默认读 ``OFFLINE_COMPANION_CLOUD_MODEL`` 或 ``gpt-3.5-turbo``。
        timeout: HTTP 超时秒数。

    返回值：
        ``CloudCompletionResponse``。

    异常：
        CloudConnectorError：配置缺失、依赖未安装或 HTTP/解析失败。

    说明：
        ``OFFLINE_COMPANION_CLOUD_STUB=1`` 时不发真实 HTTP，返回固定英文句供 B4/降级测试。
    """
    if _use_cloud_stub():
        return CloudCompletionResponse(
            text="OK. Here is a brief cloud reply for testing.",
            raw={"stub": True, "purpose": request.purpose},
        )

    resolved_url = (url or os.environ.get("OFFLINE_COMPANION_CLOUD_URL") or "").strip()
    if not resolved_url:
        raise CloudConnectorError("未配置 OFFLINE_COMPANION_CLOUD_URL")

    resolved_key = api_key if api_key is not None else os.environ.get("OFFLINE_COMPANION_CLOUD_API_KEY")
    resolved_model = (
        model or os.environ.get("OFFLINE_COMPANION_CLOUD_MODEL") or "gpt-3.5-turbo"
    ).strip()

    try:
        import httpx
    except ImportError as e:
        raise CloudConnectorError("请安装云端依赖: pip install '.[cloud]'") from e

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": f"Purpose: {request.purpose}. Reply concisely."},
            {"role": "user", "content": request.user_message},
        ],
        "max_tokens": 256,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(resolved_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise CloudConnectorError(f"云端请求失败: {e}") from e

    text = _extract_text_from_response(data)
    if not text.strip():
        raise CloudConnectorError(f"云端响应无文本: {json.dumps(data, ensure_ascii=False)[:500]}")
    return CloudCompletionResponse(text=text.strip(), raw=data if isinstance(data, dict) else {"raw": data})


def _extract_text_from_response(data: Any) -> str:
    """摘要：兼容 OpenAI chat/completions 与 ``{"text": "..."}`` 简易格式。"""
    if isinstance(data, dict):
        if isinstance(data.get("text"), str):
            return data["text"]
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    return msg["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
    return ""
