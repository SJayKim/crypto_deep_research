# Shared image for every service (mcp, the 4 workers, orchestrator). Each compose
# service runs the same image with a different command + env (M5 packaging).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install deps first (cached unless pyproject/lock change). --no-dev drops test tooling;
# uvicorn is a runtime dep so workers can serve.
COPY pyproject.toml uv.lock ./
# Opt-in escape hatch for networks with TLS interception: pass
#   --build-arg UV_INSECURE_HOST="pypi.org files.pythonhosted.org"
# to skip cert verification for PyPI during this build only. Default empty = a normal,
# fully-verified build everywhere else.
ARG UV_INSECURE_HOST=""
RUN if [ -n "$UV_INSECURE_HOST" ]; then \
      flags=""; for h in $UV_INSECURE_HOST; do flags="$flags --allow-insecure-host $h"; done; \
      uv sync --frozen --no-dev $flags; \
    else \
      uv sync --frozen --no-dev; \
    fi

COPY crypto_deep_research ./crypto_deep_research

ENV PATH="/app/.venv/bin:$PATH"
