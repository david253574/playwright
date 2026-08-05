#!/bin/bash

# Navigate to the correct directory just in case
cd /opt/render/project/src || exit

# Ensure persistent JSON files are stored in the mounted disk (user_data)
# so they survive Render deployments and restarts.
mkdir -p user_data
FILES=("profiles.json" "scheduled_queue.json" "communities_cache.json" "daily_post_history.json" "auto_responder_config.json")

for f in "${FILES[@]}"; do
    # If the file exists in root but NOT in user_data, move it (migrate)
    if [ -f "$f" ] && [ ! -L "$f" ]; then
        if [ ! -f "user_data/$f" ]; then
            mv "$f" "user_data/$f"
        fi
    fi
    # Remove the root file/symlink and create a fresh symlink to the persistent disk
    rm -f "$f"
    ln -s "user_data/$f" "$f"
done

# Run the background worker as a background process
echo "Starting background worker..."
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" python background_worker.py &

# Run the Streamlit web interface in the foreground
echo "Starting Streamlit web app..."
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" streamlit run app.py --server.port $PORT --server.address 0.0.0.0
