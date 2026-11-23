FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EPP_DATA_DIR=/data \
    EPP_STATIC_DIR=/app/static \
    APP_VERSION=$APP_VERSION

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . \
    && useradd --system --uid 10001 --home /app epp \
    && mkdir -p /data && chown epp /data
COPY --from=web /web/dist ./static

USER epp
VOLUME ["/data"]
EXPOSE 3081

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3081/health')" || exit 1

ENTRYPOINT ["epp"]
CMD ["serve"]
