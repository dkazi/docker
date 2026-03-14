#!/bin/bash

# 1. Υπηρεσίες Ubuntu
service rsyslog start
service apache2 start

# 2. Το Flask API (για να δέχεται τα logs)
python3 backend_api.py &

# 3. Ο Watchdog (για να στέλνει τα logs)
python3 bridge.py &

# 4. Το Streamlit (το GUI μας)
streamlit run app.py --server.port=8501 --server.address=0.0.0.0
