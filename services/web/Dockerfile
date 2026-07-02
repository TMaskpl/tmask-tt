FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

RUN mkdir -p /app/staticfiles \
    && addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]

# dev: adds pytest/factory-boy on top of base — used only for running tests,
# never deployed. Keeps pytest (and its own CVEs) out of the production image.
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
USER app

# production: default target, no test tooling installed
FROM base AS production
USER app
