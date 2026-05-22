# 本地推理：CUDA 安装与性能基线

> **适用**：`llama-cpp-python` + GGUF（默认 **Qwen2.5-1.5B-Instruct Q4_K_M**）  
> **分层**：实现位于 **C1**（`runtime/inference_backend`）；本文仅为运维与验收指引，不改动架构边界。

---

## 一、为何需要 CUDA 版 wheel

若安装的是 **CPU 版** `llama-cpp-python`，即使设置 `n_gpu_layers=99`，推理仍可能在 CPU 上运行，表现为：

- `check-model` 显示 `n_gpu_layers=99` 但单轮耗时 **数十秒～百余秒**（1.5B 模型也不正常）
- `nvidia-smi` 在推理时 **GPU 利用率接近 0**

**结论**：体验档目标平台（Windows / Linux + NVIDIA）应安装 **与 CUDA 驱动匹配** 的预编译 wheel 或自行带 `CMAKE_ARGS=-DLLAMA_CUDA=on` 编译。

---

## 二、安装指引

### 2.1 Linux（含 AutoDL）

```bash
source .venv/bin/activate
# 先确认驱动与 CUDA 运行时可用
nvidia-smi

# 方式 A：官方 CUDA wheel（版本以 llama-cpp-python 发布页为准）
pip install llama-cpp-python --upgrade --force-reinstall \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124

# 方式 B：源码编译（CUDA 工具链齐全时）
# CMAKE_ARGS="-DLLAMA_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

pip install -e ".[inference]"
python -m offline_companion check-model --model "$OFFLINE_COMPANION_GGUF" --n-gpu-layers 99 --n-ctx 512
```

### 2.2 Windows

1. 安装 **NVIDIA 驱动**（与显卡匹配）。  
2. 使用 **Python 3.11**（仓库官方支持版本）。  
3. 在 venv 中安装 CUDA wheel（索引 URL 以 [llama-cpp-python](https://github.com/abetlen/llama-cpp-python/releases) 当前文档为准），例如：

```powershell
.\.venv\Scripts\Activate.ps1
pip install llama-cpp-python --upgrade --force-reinstall `
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
pip install -e ".[inference]"
python -m offline_companion check-model --model C:\path\model.gguf --n-gpu-layers 20 --n-ctx 512
```

4. 聊天时传入与 `check-model` 一致的 `--n-gpu-layers`。

---

## 三、性能基线（体验档参考）

| 指标 | Qwen2.5-1.5B Q4_K_M | 说明 |
|------|---------------------|------|
| `n_ctx` | 2048（可降至 512 做 smoke） | 越大越占显存/内存 |
| `n_gpu_layers` | 尽量全层 offload（如 99） | 以 `check-model` 无 OOM 为准 |
| 单轮延迟（CUDA 正常） | **目标 &lt; 30s**（短句、单轮生成） | 验收仅 **WARN**，不阻塞 CI |
| 单轮延迟（仅 CPU） | 可能 **60～120s+** | 功能可用，非体验档 |

在 `scripts/gpu_acceptance.py` 全量跑通时，若单轮超过阈值，应优先排查 **wheel 是否为 CUDA 版**，而非先调模型参数。

---

## 四、观测与长跑（Sprint 4+）

建议在具备 GPU 的环境偶尔执行：

```bash
python scripts/gpu_acceptance.py --root .
```

可选（计划中的 `scripts/stress_test.py`）：

- 连续 **N 轮** 短对话（如 N=50～100）
- 记录进程 **RSS**、单轮 **wall time**、`companion.db` / `knowledge.db` 文件大小
- 用于发现 Python/原生库泄漏或 SQLite 膨胀趋势（**不**作为当前 CI 硬门禁）

---

## 五、环境变量

| 变量 | 用途 |
|------|------|
| `OFFLINE_COMPANION_GGUF` | `gpu_acceptance` / 全量验收用的模型路径 |
| `OFFLINE_COMPANION_N_GPU_LAYERS` | 覆盖默认 GPU 层数（如 `99`） |

---

## 六、相关文档

- 技术栈：[`tech-stack-v1.0.md`](./tech-stack-v1.0.md) §二  
- 项目状态与验收：[`PROJECT_STATUS.md`](./PROJECT_STATUS.md)  
- Docker（无 GPU 逻辑验收）：[`docker.md`](./docker.md)
