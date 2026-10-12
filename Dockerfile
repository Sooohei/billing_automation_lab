# Web アプリと 1 時間ごとのバッチで共通のイメージ
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 依存パッケージだけを先に入れ、ソースの変更でこの層を作り直さないようにする
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY sample_data ./sample_data
COPY app ./app

EXPOSE 8000

# Web アプリを起動する。バッチは `python -m app.jobs.hourly` を指定して実行する
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
