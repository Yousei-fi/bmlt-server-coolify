FROM python:3.12-slim

# OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Supercronic (cron runner)
ADD https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN chmod +x /usr/local/bin/supercronic

# Copy importer code
COPY sync_wp_to_bmlt_v4.py /app/sync_wp_to_bmlt_v4.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Runtime defaults
ENV SYNC_INTERVAL_MINUTES=30
ENV DATA_DIR=/data

VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]

