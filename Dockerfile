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

FROM python:3.12-slim AS api
WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY app/ /app/app/

# Copy the shared swarm-oversight package
COPY swarm-oversight/ /app/swarm-oversight/

# Default env (override at runtime)
ENV PAYPAL_CLIENT_ID="" \
    PAYPAL_SECRET=""

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
