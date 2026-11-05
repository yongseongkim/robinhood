FROM node:24-bookworm-slim AS web
WORKDIR /build/robinhood-web
COPY robinhood-web/package*.json ./
RUN npm ci
COPY robinhood-web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/robinhood-server/src \
    ROBINHOOD_VAR=/tmp/robinhood
WORKDIR /app
# 소스 경로를 유지해야 Settings의 저장소 상대 경로가 /app을 가리킨다.
COPY robinhood-server/pyproject.toml robinhood-server/pyproject.toml
COPY robinhood-server/src/ robinhood-server/src/
RUN pip install --no-cache-dir ./robinhood-server \
    && groupadd --gid 10001 robinhood \
    && useradd --uid 10001 --gid robinhood --no-create-home robinhood
LABEL org.opencontainers.image.source="https://github.com/yongseongkim/robinhood"

FROM runtime AS api
COPY --from=web /build/robinhood-web/dist/ /app/robinhood-web/dist/
USER 10001:10001
EXPOSE 8000
CMD ["robinhood", "serve", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       chromium fonts-noto-cjk tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY pipeline/requirements.txt /app/pipeline/requirements.txt
RUN pip install --no-cache-dir -r /app/pipeline/requirements.txt
COPY pipeline/ /app/pipeline/
# 원본·지도 중간 결과·작업 로그를 하나의 영구 볼륨에 보관한다.
RUN mkdir -p /app/site /storage \
    && ln -s /storage/data /app/data \
    && ln -s /storage/site-data /app/site/data \
    && chown 10001:10001 /storage
ENV ROBINHOOD_VAR=/storage/var \
    ROBINHOOD_COLLECTOR_PYTHON=/usr/local/bin/python \
    ROBINHOOD_BROWSER_EXECUTABLE=/usr/bin/chromium \
    HOME=/tmp
USER 10001:10001
CMD ["sh", "-ec", "mkdir -p /storage/data /storage/site-data /storage/var; exec robinhood worker --interval-hours 24"]
