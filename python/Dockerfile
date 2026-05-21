FROM python:3.12-slim

# Stream stdout/stderr unbuffered so Railway (and any docker logs viewer) sees
# print/logging output in real time. Without this Python block-buffers when
# not attached to a TTY and the container appears to do nothing for minutes.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy lockfile so `uv sync --frozen` installs the exact pinned versions
# (notably lightgbm 4.6.0). Without --frozen + uv.lock, uv re-resolves and
# may pick newer patches that break pickle compatibility with the trained model.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

CMD ["uv", "run", "main.py"]
    