# Sift backend — Django + DRF + agent loop.
# Build from the REPO ROOT so the agent workspace can be baked in:
#   docker build -f backend/Dockerfile .
# Locally use docker-compose.yml; the same image deploys to Cloudflare
# Containers (wrangler builds it via your local Docker daemon).

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend/ ./
# Agent workspace jail (AGENT.md, connectors/, schemas/, workflows/, runs/).
# Mounted over in compose for live editing; baked in for cloud deploys.
COPY workspace/ /workspace/
ENV AGENT_WORKSPACE_ROOT=/workspace

EXPOSE 8000

# gthread workers: SSE streaming (agent chat) needs threads, and pipeline
# runs spawn daemon threads inside the worker process.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 8 --timeout 120"]
