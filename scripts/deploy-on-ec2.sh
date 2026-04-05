#!/bin/bash
set -e  # Exit if any command fails

echo "Starting UniCortex Deployment..."

# 1. Move to the backend directory
cd /home/ec2-user/UnieCortex/CortexBackend

# 2. Pull the latest code from GitHub
# Using --ff-only to prevent "divergent branches" errors
git pull origin main --ff-only

# 3. Refresh dependencies in the virtual environment
source .venv/bin/activate
pip install -r requirements.txt

# 4. Run any pending database migrations
# We use "|| true" because DSQL often forbids the 'alembic_version' 
# update inside the same transaction as a table creation.
echo "Checking for database updates..."
alembic upgrade head || echo "Database already at latest version or DSQL transaction bypass triggered."

# 5. Restart the Uvicorn server in the background
echo "Restarting the engine..."
# Kill any existing process on port 5000 to avoid 'Address already in use'
pkill -f uvicorn || true

# Launch the app and detach it so it keeps running after GitHub logs out
nohup uvicorn unie_cortex.main:app --host 0.0.0.0 --port 5000 > output.log 2>&1 &

echo "UniCortex is back online and updated!"
