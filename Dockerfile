FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV SECRET_KEY=english-scenario-production-2026
ENV PORT=5000
ENV FLASK_ENV=production

EXPOSE 5000

VOLUME ["/app/data"]

RUN mkdir -p /app/data /app/data/tts_cache

CMD ["python", "app.py"]
