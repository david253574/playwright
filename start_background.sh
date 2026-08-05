#!/bin/bash
echo "Starting Streamlit in the background with Xvfb..."
nohup xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" venv/bin/streamlit run app.py > streamlit.log 2>&1 &
echo "Streamlit is now running in the background. Check streamlit.log for output."