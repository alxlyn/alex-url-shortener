FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Run as a normal user, not root.
RUN useradd --create-home appuser
USER appuser

ENV PORT=8080
ENV PATH="/app/.venv/bin:$PATH"
# exec so uvicorn gets the stop signal directly and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
