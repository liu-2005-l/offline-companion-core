# Docker 开发环境（Sprint 3）

> 用于锁定 Python 3.11 与依赖版本；**不**将对话服务暴露到公网。

## 构建与进入

```bash
cd ~/offline-companion-core
docker compose build
docker compose run --rm companion-dev bash
```

容器内（冷启动验收，无 GPU）：

```bash
cd /app
pip install -e ".[dev,cloud]"
python scripts/full_acceptance.py --skip-gpu
```

## Volume 建议

| 挂载点 | 用途 |
|--------|------|
| `/data/models` | GGUF（只读） |
| `/data/knowledge` | 自备语料与 `knowledge.db` |
| `/data/app` | `companion.db` 与导出 |

宿主机示例：

```bash
export OFFLINE_COMPANION_GGUF=/data/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
python scripts/ingest_knowledge.py /data/knowledge/corpus.jsonl --db /data/knowledge/knowledge.db
```

## GPU 说明

基础镜像为 `python:3.11-slim`。在 AutoDL 等 GPU 宿主机上，推荐**直接在宿主机 venv** 安装 CUDA 版 `llama-cpp-python` 并运行 `full_acceptance.py`；或在自定义 CUDA 基础镜像中扩展本 `Dockerfile`。
