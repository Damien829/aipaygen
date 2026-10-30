FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN rm -rf venv/ .env .env.enc *.db tests/ __pycache__/ .git/

EXPOSE 5001

ENV PYTHONUNBUFFERED=1

CMD ["gunicorn", "--workers", "4", "--worker-class", "sync", "--bind", "0.0.0.0:5001", "--timeout", "120", "app:app"]
