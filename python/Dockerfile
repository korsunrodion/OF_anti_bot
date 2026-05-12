FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy lockfile so `uv sync --frozen` installs the exact pinned versions
# (notably lightgbm 4.6.0). Without --frozen + uv.lock, uv re-resolves and
# may pick newer patches that break pickle compatibility with the trained model.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

CMD ["uv", "run", "main.py"]
    