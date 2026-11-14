# AiPayGen core (v1 marketplace). One image, three processes, chosen by compose:
# web (gunicorn), scheduler (run_scheduler.py), mcp (mcp_server.py --http).
FROM python:3.11.17-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    AIPAYGEN_DATA_DIR=/data

WORKDIR /app

# Exact versions from the lock (Linux gets cryptography 50 / pyOpenSSL 26.4).
COPY requirements.lock .
RUN pip install --no-deps -r requirements.lock

COPY . .

RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /data \
    && chown app:app /data
USER app

EXPOSE 5001 5002
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
