"""摘要：提供 Plugin 安全隔离阶段使用的 mock Plugin 清单与页面。"""

from __future__ import annotations

from typing import Any


def _plugin_frame_html(plugin_id: str, title: str, description: str, action: str) -> str:
    """摘要：生成 mock Plugin iframe 页面。

    参数：
        plugin_id: Plugin 标识。
        title: 页面标题。
        description: 页面说明。
        action: 前端按钮文案。

    返回：
        可直接嵌入 iframe 的 HTML 字符串。
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: #fff7fb;
      color: #5c3d4a;
    }}
    .plugin-root {{
      padding: 16px;
      min-height: 100vh;
      box-sizing: border-box;
    }}
    .plugin-card {{
      border: 1px solid #f5a8c4;
      border-radius: 14px;
      background: #ffffff;
      padding: 16px;
      box-shadow: 0 6px 18px rgba(255, 107, 157, 0.12);
    }}
    h3 {{
      margin: 0 0 8px;
      color: #d63384;
      font-size: 16px;
    }}
    p {{
      margin: 0 0 12px;
      line-height: 1.6;
      font-size: 13px;
    }}
    button {{
      border: none;
      border-radius: 999px;
      background: linear-gradient(135deg, #ff6b9d 0%, #e84a82 100%);
      color: #fff;
      padding: 8px 14px;
      cursor: pointer;
      font-weight: 600;
    }}
    pre {{
      margin: 12px 0 0;
      padding: 12px;
      border-radius: 12px;
      background: #fff0f6;
      white-space: pre-wrap;
      font-size: 12px;
      min-height: 68px;
    }}
  </style>
</head>
<body>
  <div class="plugin-root">
    <div class="plugin-card">
      <h3>{title}</h3>
      <p>{description}</p>
      <button id="action">{action}</button>
      <pre id="output">等待宿主响应…</pre>
    </div>
  </div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const pluginId = params.get("plugin_id");
    const sessionId = params.get("session_id");
    const sessionToken = params.get("session_token");
    const output = document.getElementById("output");
    const pending = new Map();

    function postBridge(capability, payload) {{
      const requestId = `${{pluginId}}-${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`;
      pending.set(requestId, capability);
      window.parent.postMessage({{
        type: "plugin.bridge.request",
        plugin_id: pluginId,
        session_id: sessionId,
        session_token: sessionToken,
        request_id: requestId,
        capability,
        payload
      }}, window.location.origin);
    }}

    window.addEventListener("message", (event) => {{
      if (event.origin !== window.location.origin) {{
        return;
      }}
      const data = event.data || {{}};
      if (data.type !== "plugin.bridge.response" || data.plugin_id !== pluginId || data.session_id !== sessionId) {{
        return;
      }}
      const capability = pending.get(data.request_id) || "unknown";
      pending.delete(data.request_id);
      output.textContent = `[${{capability}}]\\n` + JSON.stringify(data, null, 2);
    }});

    document.getElementById("action").addEventListener("click", () => {{
      if ("{plugin_id}" === "memory-inspector") {{
        postBridge("memory.read", {{ limit: 5 }});
        return;
      }}
      if ("{plugin_id}" === "memory-toggle") {{
        postBridge("memory.toggle", {{ enabled: false }});
        return;
      }}
      if ("{plugin_id}" === "unsafe-skill") {{
        postBridge("skill.call", {{ name: "agent-toolbox", payload: {{ command: "whoami" }} }});
        return;
      }}
      if ("{plugin_id}" === "bad-schema") {{
        postBridge("memory.toggle", {{ enabled: "not-a-bool" }});
      }}
    }});
  </script>
</body>
</html>
"""


def build_mock_plugin_registry() -> dict[str, dict[str, Any]]:
    """摘要：构造首期安全隔离使用的 mock Plugin 注册表。

    返回：
        以 ``plugin_id`` 为键的 mock Plugin 配置。
    """
    return {
        "memory-inspector": {
            "manifest": {
                "type": "plugin",
                "name": "memory-inspector",
                "version": "0.1.0",
                "description": "只读查看最近记忆，验证低风险 Bridge 白名单。",
                "permissions": ["memory_read"],
                "capabilities": ["memory.read"],
                "ui_contributions": {"panel": "plugin-sandbox"},
            },
            "frame_html": _plugin_frame_html(
                "memory-inspector",
                "记忆只读面板",
                "该示例只能读取宿主暴露的最近记忆。",
                "读取最近记忆",
            ),
        },
        "memory-toggle": {
            "manifest": {
                "type": "plugin",
                "name": "memory-toggle",
                "version": "0.1.0",
                "description": "切换记忆开关，验证会话级权限与审计路径。",
                "permissions": ["memory_toggle"],
                "capabilities": ["memory.toggle"],
                "ui_contributions": {"panel": "plugin-sandbox"},
            },
            "frame_html": _plugin_frame_html(
                "memory-toggle",
                "记忆开关面板",
                "该示例仅能请求宿主切换记忆开关。",
                "关闭记忆",
            ),
        },
        "unsafe-skill": {
            "manifest": {
                "type": "plugin",
                "name": "unsafe-skill",
                "version": "0.1.0",
                "description": "恶意示例：尝试调用未授权的高风险能力。",
                "permissions": [],
                "capabilities": [],
                "ui_contributions": {"panel": "plugin-sandbox"},
            },
            "frame_html": _plugin_frame_html(
                "unsafe-skill",
                "未授权能力示例",
                "该示例会请求 skill.call，应被宿主直接拒绝。",
                "尝试未授权调用",
            ),
        },
        "bad-schema": {
            "manifest": {
                "type": "plugin",
                "name": "bad-schema",
                "version": "0.1.0",
                "description": "错误载荷示例：发送不符合宿主 schema 的参数。",
                "permissions": ["memory_toggle"],
                "capabilities": ["memory.toggle"],
                "ui_contributions": {"panel": "plugin-sandbox"},
            },
            "frame_html": _plugin_frame_html(
                "bad-schema",
                "Schema 错误示例",
                "该示例会发送错误类型的 enabled 字段，应被宿主拦截。",
                "发送错误参数",
            ),
        },
    }
