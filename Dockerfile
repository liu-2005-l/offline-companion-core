# 开发/验收镜像（Sprint 3）；对话仍须在容器内手动 exec，不暴露公网端口
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY fixtures ./fixtures
COPY scripts ./scripts
COPY tests ./tests

RUN pip install -U pip wheel && pip install -e ".[dev,cloud]"

# 推理 CUDA 版需在宿主机/GPU 镜像中另行安装: pip install llama-cpp-python (CUDA wheel)
# 模型与语料通过 volume 挂载，见 docker-compose.yml

CMD ["bash"]
