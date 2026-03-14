#!/bin/bash
set -e

echo "[LogGuard] Starting Flask backend..."
python3 backend_api.py &

echo "[LogGuard] Waiting for backend to be ready..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
        echo "[LogGuard] Backend ready."
        break
    fi
    sleep 1
done

echo "[LogGuard] Starting Streamlit..."
exec streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
