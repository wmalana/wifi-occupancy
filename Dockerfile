FROM python:3.12-slim

WORKDIR /app

# System deps for ncclient/paramiko/lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt-dev openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Data and config are mounted as volumes at runtime
RUN mkdir -p /app/data /app/config

ENV DB_PATH=/app/data/occupancy.db
ENV SITES_CONFIG=/app/config/sites.yaml

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
