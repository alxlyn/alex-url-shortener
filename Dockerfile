FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Don't run as root.
RUN useradd --create-home appuser
USER appuser

ENV PORT=8080
ENV PATH="/app/.venv/bin:$PATH"
# exec so uvicorn gets the stop signal directly and shuts down cleanly.
# --no-proxy-headers: the app reads X-Forwarded-For itself (TRUSTED_PROXY_HOPS).
# Left on, uvicorn would rewrite the client address from that header first.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --no-proxy-headers"]
