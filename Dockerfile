# Qoima — production image (gunicorn). Build: docker build -t qoima .
# Run:   docker run -p 8000:8000 --env-file .env qoima      (or: docker compose up)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000
WORKDIR /app

# dependencies first: this layer is reused until requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY wsgi.py .

# never run the web server as root
RUN useradd --create-home --uid 10001 qoima && chown -R qoima /app
USER qoima

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)"

CMD ["sh", "-c", "exec gunicorn wsgi:app --workers 2 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT} --access-logfile -"]
