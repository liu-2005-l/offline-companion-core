#!/usr/bin/env python3
"""端到端记忆验证脚本：真实模型跑完整记忆写入→召回链路。

定位：
    验证记忆系统在真实推理环境下的完整链路，包括：
    1. 记忆写入（画像记忆）
    2. 确定性回答（身份查询）
    3. 记忆召回（不同表述方式）

验收标准：
    - 写入"以后你叫立华奏"后，询问身份时必须返回"立华奏"
    - 支持多种询问方式："你叫什么"、"你叫啥"、"你的名字"
    - 真实 GGUF 模型完整推理流程

用法：
    python scripts/e2e_memory_check.py
    python scripts/e2e_memory_check.py --model models/qwen2.5-1.5b-instruct-q4_k_m.gguf
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# 显式加入 src 路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.backend import LlamaCppBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.runtime_paths import configs_dir


def _find_default_model() -> Path | None:
    """查找默认 GGUF 模型文件。"""
    candidates = [
        ROOT / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        ROOT / "models" / "qwen2.5-7b-instruct-q4_k_m.gguf",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _configure_stdio_utf8() -> None:
    """Windows 控制台中文输出兼容。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    """执行端到端记忆验证。"""
    _configure_stdio_utf8()

    parser = argparse.ArgumentParser(description="端到端记忆验证")
    parser.add_argument("--model", type=Path, help="GGUF 模型路径")
    parser.add_argument("--persona", type=Path, help="人设配置路径")
    args = parser.parse_args()

    # 1. 定位模型文件
    model_path = args.model or _find_default_model()
    if model_path is None or not model_path.is_file():
        print("[ERROR] 未找到可用的 GGUF 模型文件", file=sys.stderr)
        print("请使用 --model 指定模型路径，或将模型放入 models/ 目录", file=sys.stderr)
        return 1

    print(f"使用模型: {model_path}")

    # 2. 加载人设
    persona_path = args.persona or (configs_dir() / "personas" / "default.yaml")
    if not persona_path.is_file():
        persona_path = ROOT / "configs" / "personas" / "default.yaml"
    if not persona_path.is_file():
        print(f"[ERROR] 人设文件不存在: {persona_path}", file=sys.stderr)
        return 1

    print(f"加载人设: {persona_path}")
    persona = load_persona_file(persona_path)

    # 3. 初始化推理后端
    print("初始化推理后端...")
    try:
        backend = LlamaCppBackend(
            model_path=str(model_path),
            n_ctx=2048,
            n_gpu_layers=0,  # CPU 模式，确保跨平台可运行
        )
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        print(f"[ERROR] 推理后端初始化失败: {e}", file=sys.stderr)
        return 1

    # 4. 创建临时数据库
    with tempfile.TemporaryDirectory(prefix="e2e_memory_") as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        print(f"临时数据库: {db_path}")

        conn = connect(db_path)
        session_id = "e2e_test_session"
        new_session(conn, session_id, persona.persona_id, title="E2E Memory Test")

        try:
            session = PersonaSessionCore(persona)

            print("\n" + "=" * 60)
            print("阶段 1: 写入画像记忆")
            print("=" * 60)

            # 5. 写入画像记忆
            memory_input = "以后你叫立华奏"
            print(f"用户输入: {memory_input}")

            decision = MemoryLifecycleManager.decide_memory(memory_input)
            print(f"决策结果: route={decision.route}, should_store={decision.should_store}")

            if decision.should_store and decision.memory_item:
                MemoryLifecycleManager.add_memory_chunk(
                    conn,
                    session_id=session_id,
                    source="e2e_test",
                    body=decision.memory_item["body"],
                    meta=decision.memory_item.get("meta_json", {}),
                )
                conn.commit()
                print("[OK] 画像记忆已写入")
            else:
                print("[ERROR] 记忆写入失败：决策未通过", file=sys.stderr)
                return 1

            # 6. 验证画像记忆读取
            profile = MemoryLifecycleManager.latest_profile_memory(conn)
            agent_name = profile.get("assistant", {}).get("display_name")
            print(f"读取画像: agent_name={agent_name}")

            if agent_name != "立华奏":
                print(f"[ERROR] 画像记忆读取失败，期望 '立华奏'，实际 '{agent_name}'", file=sys.stderr)
                return 1

            print("\n" + "=" * 60)
            print("阶段 2: 确定性回答验证")
            print("=" * 60)

            # 7. 测试多种询问方式
            test_queries = [
                "你叫什么",
                "你叫啥",
                "你的名字",
                "你是谁",
            ]

            for i, query in enumerate(test_queries, 1):
                print(f"\n测试 {i}/{len(test_queries)}: {query}")

                result = session.assemble_reply(
                    backend=backend,
                    conn=conn,
                    user_message=query,
                    history=[],
                    memory_enabled=True,
                    max_tokens=128,
                )

                reply = result.reply.strip()
                print(f"回复: {reply}")

                # 验证回复包含"立华奏"
                if "立华奏" not in reply:
                    print("[FAIL] 回复未包含期望名字 '立华奏'", file=sys.stderr)
                    print(f"  查询: {query}", file=sys.stderr)
                    print(f"  回复: {reply}", file=sys.stderr)
                    return 1

                print("[OK] 确定性回答正确")

            print("\n" + "=" * 60)
            print("验证通过：所有测试项通过")
            print("=" * 60)
            return 0

        finally:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
