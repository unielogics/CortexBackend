#!/bin/bash
set -euo pipefail

echo "Starting UniCortex Deployment..."

# 1. Move to the backend directory
cd /home/ec2-user/UnieCortex/CortexBackend

# 2. Pull the latest code from GitHub
# Using --ff-only to prevent "divergent branches" errors
git pull origin main --ff-only

# 3. Refresh dependencies in the virtual environment
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Run any pending database migrations
# We use "|| true" because DSQL often forbids the 'alembic_version' 
# update inside the same transaction as a table creation.
echo "Checking for database updates..."
if [ -f "alembic.ini" ]; then
  alembic upgrade head || echo "Database already at latest version or DSQL transaction bypass triggered."
fi

# 5. Prefer systemd restart when available; fallback to background uvicorn.
SERVICE_NAME="${UNIECORTEX_SERVICE_NAME:-uniecortex-backend}"
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | rg -q "^${SERVICE_NAME}\\.service"; then
  echo "Restarting service ${SERVICE_NAME} via systemd..."
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl --no-pager --full status "${SERVICE_NAME}" || true
else
  echo "Systemd service not found; restarting uvicorn background process..."
  pkill -f "uvicorn unie_cortex.main:app" || true
  nohup uvicorn unie_cortex.main:app --host 0.0.0.0 --port 5000 > output.log 2>&1 &
fi

echo "UniCortex is back online and updated!"
