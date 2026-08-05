#!/bin/bash

# Navigate to the correct directory just in case
cd /opt/render/project/src || exit

# Run the background worker as a background process
echo "Starting background worker..."
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" python background_worker.py &

# Run the Streamlit web interface in the foreground
echo "Starting Streamlit web app..."
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" streamlit run app.py --server.port $PORT --server.address 0.0.0.0
