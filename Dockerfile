FROM python:3.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home app

FROM base AS runtime
COPY --chown=10001:10001 ingestflow ./ingestflow
COPY --chown=10001:10001 migrations ./migrations
USER 10001:10001
EXPOSE 8100
CMD ["python", "-m", "uvicorn", "ingestflow.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1", "--no-access-log", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]

FROM runtime AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY --chown=10001:10001 tests ./tests
COPY --chown=10001:10001 docs/openapi.json ./docs/openapi.json
COPY --chown=10001:10001 pytest.ini .
COPY --chown=10001:10001 scripts/smoke.py ./scripts/smoke.py
COPY --chown=10001:10001 scripts/export_openapi.py ./scripts/export_openapi.py
USER 10001:10001
CMD ["python", "-m", "pytest", "--basetemp=/tmp/pytest", "-p", "no:cacheprovider"]
