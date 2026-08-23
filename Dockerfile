# ── 企业知识助手 RAG · 生产镜像 ─────────────────────────────
# 构建:  docker build -t rag-enterprise .
# 运行:  docker compose up -d   (推荐,自带健康检查/日志轮转/数据持久化)

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 生产建议显式注入 SECRET_KEY(JWT 签名 + settings.json 加密),
    # 否则首次启动自动生成 data/.secret 并持久化(单实例够用)。
    SECRET_KEY=${SECRET_KEY:-}

WORKDIR /app

# torch 需要 libgomp 动态库,否则 import 时 DLL 报错
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 先装 torch CPU 版(官方 CPU wheel,省 ~1.5GB CUDA 依赖),再装其余
# --index-url 只对 torch 生效,其余依赖仍从默认 PyPI 拉取
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# 多 worker:JWT/数据库/索引跨进程共享(SQLite 落盘);限流是进程内计数,
# 多 worker 时每分钟上限为 workers × N —— 需要严格上限再加 Redis。
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
