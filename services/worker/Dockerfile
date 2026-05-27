FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync openssh-client libpq-dev gcc gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY services/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Worker code + Django apps/settings from web service (shared models and config)
COPY services/worker/ .
COPY services/web/config ./config
COPY services/web/apps ./apps
COPY services/web/utils ./utils
COPY services/web/templates ./templates

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app
USER app

CMD ["celery", "-A", "tasks", "worker", "--loglevel=info", "--concurrency=4"]
