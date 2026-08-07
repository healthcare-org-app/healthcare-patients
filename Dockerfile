FROM python:3.11-slim

WORKDIR /app

# The shared runtime lives at ../../libs/py-healthcare-common in the monorepo.
# For a standalone repo, this Dockerfile is built with the lib either
# vendored, published to a private index, or built at CI time. In dev,
# `docker compose` bind-mounts the lib in place.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY service.yaml ./
COPY tests/ ./tests/

ENV PYTHONUNBUFFERED=1
ENV PORT=8100

EXPOSE 8100

CMD ["python", "-m", "app.main"]
