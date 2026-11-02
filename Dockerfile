# syntax=docker/dockerfile:1
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir -r requirements.txt; fi
COPY *.py ./
RUN git clone https://github.com/cryptobro1985-prog/pandora-testnet.git /app/codex_engine && cd /app/codex_engine && git checkout a01bc1d0c9c216ddb28c75b31fb42e1248867a0d && rm -rf .git
COPY pandora_beda/ ./pandora_beda/
EXPOSE 10000
CMD ["python","app.py"]
