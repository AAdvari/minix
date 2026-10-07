FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install "__MINIX_PIP_SPEC__"

COPY . .

ENV PYTHONUNBUFFERED=1 \
    MINIX_SETTINGS_MODULE=config \
    APP_PORT=__APP_PORT__

# Numeric default keeps dockerfile-utils happy; `minix init` rewrites this line.
EXPOSE 8000

CMD ["sh", "-c", "uvicorn entries.api:Api --host 0.0.0.0 --port ${APP_PORT}"]
