# syntax=docker/dockerfile:1.7
# API, outbox worker (default target "api") and tools (seed, evaluation, training) from one file:
#   docker build -f backend/Dockerfile --target api   -t kanzlei-api .
#   docker build -f backend/Dockerfile --target tools -t kanzlei-tools .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    KANZLEI_CONFIG_DIR=/app/config KANZLEI_REPORTS_DIR=/app/reports
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/src backend/src

FROM base AS api
RUN pip install "./backend[s3]" && useradd --uid 10001 --no-create-home kanzlei
COPY config config
COPY reports/evaluation.json reports/evaluation.json
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["uvicorn", "kanzlei.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM base AS tools
RUN pip install "./backend[sim,s3]"
COPY config config
COPY reports reports
ENTRYPOINT ["python", "-m", "kanzlei_sim"]
CMD ["seed"]
