FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /workspace

FROM backend-base AS backend-deps
COPY tabletop-twin/backend/pyproject.toml tabletop-twin/backend/
COPY tabletop-twin/backend/twin tabletop-twin/backend/twin
RUN uv pip install --system --no-cache -e "./tabletop-twin/backend[dev]"
WORKDIR /workspace/tabletop-twin/backend

FROM node:22-bookworm-slim AS web-base
ENV CI=1
WORKDIR /workspace/tabletop-twin/web

FROM web-base AS web-deps
COPY tabletop-twin/web/package.json tabletop-twin/web/package-lock.json ./
RUN ONNXRUNTIME_NODE_INSTALL_CUDA=skip npm ci
COPY tabletop-twin/web ./

FROM python:3.12-slim AS integration

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY integration/pyproject.toml integration/README.md /app/integration/
COPY integration/oversight_twin /app/integration/oversight_twin
RUN pip install --no-cache-dir -e /app/integration

COPY tabletop-twin/backend/twin /app/tabletop-twin/backend/twin
COPY swarm-oversight/swarm_oversight /app/swarm-oversight/swarm_oversight

RUN useradd --create-home --uid 10001 oversight \
 && chown -R oversight:oversight /app
USER oversight

CMD ["python", "-m", "uvicorn", "oversight_twin.api:app", "--host", "0.0.0.0", "--port", "8000"]
