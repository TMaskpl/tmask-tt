FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync openssh-client libpq-dev gcc gnupg postgresql-client default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# Microsoft apt repo for mssql-tools18 / msodbcsql18 (ODBC driver for pyodbc)
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg2 apt-transport-https \
    && curl -sSL -o /usr/share/keyrings/microsoft-prod.gpg https://packages.microsoft.com/keys/microsoft.asc \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends mssql-tools18 unixodbc-dev unixodbc msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/mssql-tools18/bin:${PATH}"

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
