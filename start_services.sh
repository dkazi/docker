#!/bin/bash
set -e

echo "[LogGuard] Starting Flask backend..."
python3 backend_api.py &
FLASK_PID=$!

# Wait for Flask to be ready before starting Streamlit
echo "[LogGuard] Waiting for backend to be ready..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:5000/status > /dev/null 2>&1; then
        echo "[LogGuard] Backend is ready."
        break
    fi
    sleep 0.5
done

echo "[LogGuard] Starting Streamlit UI..."
streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false &
STREAMLIT_PID=$!

# Keep container alive; exit if either process dies
wait -n $FLASK_PID $STREAMLIT_PID
echo "[LogGuard] A service died. Exiting."
exit 1
