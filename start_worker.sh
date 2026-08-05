#!/bin/bash
echo "Starting background worker with Xvfb..."
nohup xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" venv/bin/python background_worker.py > worker.log 2>&1 &
echo "Worker is now running in the background. Check worker.log for output."
