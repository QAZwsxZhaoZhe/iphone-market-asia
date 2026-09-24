FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    IPHONE_MARKET_DATA_DIR=/data \
    HOME=/home/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY iphone_market ./iphone_market
COPY migrations ./migrations

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /data \
    && chown -R app:app /app /data /home/app /ms-playwright

USER app

EXPOSE 8000

CMD ["iphone-platform", "serve", "--host", "0.0.0.0", "--port", "8000"]
