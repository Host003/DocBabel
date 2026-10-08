FROM python:3.11-slim AS base

# 可选构建镜像源（默认官方源，CI 不受影响）：
#   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#   --build-arg GITHUB_MIRROR=https://gh-proxy.com/
# GITHUB_MIRROR 非空时，将 https://github.com/ 重写为 <GITHUB_MIRROR>https://github.com/
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG GITHUB_MIRROR=""
# APT_MIRROR 非空时替换 Debian 源主机，如 mirrors.tuna.tsinghua.edu.cn
ARG APT_MIRROR=""

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" \
            /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    libice6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN if [ -n "$GITHUB_MIRROR" ]; then \
        git config --global url."${GITHUB_MIRROR}https://github.com/".insteadOf "https://github.com/"; \
    fi && \
    PIP_INDEX_URL="$PIP_INDEX_URL" UV_INDEX_URL="$PIP_INDEX_URL" \
        pip install --no-cache-dir uv && \
    PIP_INDEX_URL="$PIP_INDEX_URL" UV_INDEX_URL="$PIP_INDEX_URL" \
        uv pip install --system --no-cache-dir .

COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
