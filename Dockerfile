FROM node:22-bookworm-slim AS web-build

WORKDIR /web

ARG VITE_APP_BASE_PATH=/
ARG VITE_API_BASE_PATH=/api
ENV VITE_APP_BASE_PATH=${VITE_APP_BASE_PATH}
ENV VITE_API_BASE_PATH=${VITE_API_BASE_PATH}

COPY web/package.json /web/package.json
COPY web/package-lock.json /web/package-lock.json

RUN npm ci

COPY web/index.html /web/index.html
COPY web/tsconfig.json /web/tsconfig.json
COPY web/vite.config.ts /web/vite.config.ts
COPY web/src /web/src

RUN npm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STD_HEADLESS_BROWSER=true \
    STD_WORKER_HOST=0.0.0.0 \
    STD_WORKER_PORT=8765 \
    STD_CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    STD_CHROME_BINARY=/usr/bin/chromium

WORKDIR /app

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::Retries "5";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' > /etc/apt/apt.conf.d/99network-retries

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        ca-certificates \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY app /app/app
COPY docker /app/docker
COPY config.py /app/config.py
COPY config_pachong.py /app/config_pachong.py
COPY grab_module.py /app/grab_module.py
COPY search_module.py /app/search_module.py
COPY utils.py /app/utils.py
COPY run_worker.py /app/run_worker.py
COPY --from=web-build /web/dist /app/web/dist

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/artifacts /app/.tmp /app/temp_step2 /app/debug_output /app/pdf \
    && chmod +x /app/docker/start-worker.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json, urllib.request; data = json.load(urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)); raise SystemExit(0 if data.get('status') == 'ok' else 1)"

ENTRYPOINT ["/app/docker/start-worker.sh"]
