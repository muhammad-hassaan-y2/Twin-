# Build from the repository root, not from this folder: the integration imports the two
# baselines as sibling trees, so the build context has to contain all three.
#
#   docker build -f integration/Dockerfile -t oversight-twin .
#   docker compose -f integration/docker-compose.yml up --build
#
# The service fails closed: with no OVERSIGHT_API_TOKEN the authenticated routes answer
# 401 and /health says a token is missing. The container never carries a default secret.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The package is installed editable so `oversight_twin/__init__.py` still resolves its
# siblings at /app/tabletop-twin/backend and /app/swarm-oversight at import time.
COPY integration/pyproject.toml integration/README.md /app/integration/
COPY integration/oversight_twin /app/integration/oversight_twin
RUN pip install --no-cache-dir -e /app/integration

COPY tabletop-twin/backend/twin /app/tabletop-twin/backend/twin
COPY swarm-oversight/swarm_oversight /app/swarm-oversight/swarm_oversight

RUN useradd --create-home --uid 10001 oversight \
 && chown -R oversight:oversight /app
USER oversight

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; import sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# One worker on purpose: the rate meter, the runs and the model client are per process.
CMD ["python", "-m", "uvicorn", "oversight_twin.api:app", "--host", "0.0.0.0", "--port", "8000"]
