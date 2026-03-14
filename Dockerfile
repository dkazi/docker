FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# curl for the health-check in start_services.sh
# dos2unix to fix any CRLF line endings regardless of how files were edited
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client curl dos2unix \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py backend_api.py start_services.sh ./

# Force LF endings and executable bit — survives Windows git checkouts
RUN dos2unix start_services.sh && chmod +x start_services.sh

EXPOSE 8501

CMD ["./start_services.sh"]
