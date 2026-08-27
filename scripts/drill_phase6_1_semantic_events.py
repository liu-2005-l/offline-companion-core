"""摘要：重跑 Phase 6.1 语义事件真链路抽样 drill。"""

from __future__ import annotations

import logging
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offline_companion.core.memory_lifecycle.event_extractor import EventExtractor
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import CONTENT_EMBEDDING_DIMENSIONS
from offline_companion.shared.deterministic_embedding import embed_text


class FixedEventBackend:
    """摘要：返回固定结构化事件，隔离 6.1 存储链路与 LLM 随机性。"""

    def __init__(self) -> None:
        """摘要：初始化固定后端并保存收到的提示词。"""
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, temperature: float) -> str:
        """摘要：模拟结构化提取返回，保留温度断言。"""
        if temperature != 0.3:
            raise ValueError("unexpected extraction temperature")
        self.prompts.append(prompt)
        return (
            '[{"event_type":"decision","subject":"user",'
            '"content":"用户决定采用本地优先方案",'
            '"emotional_valence":0.2,"emotional_arousal":0.4,"importance":4}]'
        )


def main() -> int:
    """摘要：执行 6.1 真链路抽样并输出可审计锚点。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    with tempfile.TemporaryDirectory(prefix="oc_phase6_1_") as temp_dir:
        db_path = Path(temp_dir) / "semantic-events.db"
        conn = sqlite3.connect(db_path)
        repo = EventRepository(conn)
        backend = FixedEventBackend()
        extractor = EventExtractor(
            repo,
            backend,
            lambda text: embed_text(text, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
        )
        messages = [{"role": "user", "content": "我们决定采用本地优先方案，后续不静默上云。"}]
        first = extractor.extract(messages, "phase6-1-drill", (1, 2))
        second = extractor.extract(messages, "phase6-1-drill", (3, 4))
        if len(first) != 1:
            print(f"Phase 6.1 drill FAILED: expected first extraction=1 actual={len(first)}")
            return 1
        if second:
            print(f"Phase 6.1 drill FAILED: duplicate extraction not skipped actual={len(second)}")
            return 1
        event = repo.get(first[0].event_id)
        if event is None or event.temporal_marker != "session:phase6-1-drill:turn:1-2":
            print("Phase 6.1 drill FAILED: stored event metadata mismatch")
            return 1
        if event.content_embedding is None or len(event.content_embedding) != CONTENT_EMBEDDING_DIMENSIONS:
            print("Phase 6.1 drill FAILED: embedding dimension mismatch")
            return 1
        results = repo.vector_search(
            embed_text("本地优先方案", dimensions=CONTENT_EMBEDDING_DIMENSIONS),
            top_k=1,
        )
        if not results or results[0][0].event_id != event.event_id:
            print("Phase 6.1 drill FAILED: vector_search did not return stored event")
            return 1
        print("Phase 6.1 drill PASSED")
        print(f"- stored_events={len(repo.get_active())}")
        print(f"- duplicate_second_pass={len(second)}")
        print(f"- embedding_dim={len(event.content_embedding)}")
        print(f"- vector_top1={results[0][0].event_id}")
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
