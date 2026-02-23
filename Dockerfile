FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["uv", "run", "--no-dev", "python", "src/server.py"]
