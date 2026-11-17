FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-smart.txt .
RUN pip install --no-cache-dir -r requirements-smart.txt
COPY backend backend
COPY data data
COPY web web
RUN useradd --create-home appuser
USER appuser
ENV PORT=10000
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --limit-concurrency 40"]
