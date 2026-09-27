FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.15 \
    && uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN groupadd --gid 10001 updater \
    && useradd --uid 10001 --gid updater --no-create-home updater \
    && chown -R updater:updater /app
USER updater

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
