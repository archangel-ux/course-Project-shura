FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py .

EXPOSE 8000
CMD ["sh", "-c", "gunicorn wsgi:app --workers 2 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT:-8000}"]
