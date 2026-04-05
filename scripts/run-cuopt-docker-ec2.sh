#!/usr/bin/env bash
# Self-hosted NVIDIA cuOpt REST for Cortex (matches CUOPT_SELF_HOSTED_URL=http://127.0.0.1:8787).
# Requires: NVIDIA driver on host, Docker, and nvidia-container-toolkit so GPUs work *inside* the container.
set -euo pipefail

IMAGE="${CUOPT_IMAGE:-nvidia/cuopt:latest-cuda12.8-py312}"
NAME="${CUOPT_CONTAINER_NAME:-uniecortex-cuopt}"
HOST_PORT="${CUOPT_HOST_PORT:-8787}"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running or not accessible." >&2
  exit 1
fi

echo "Stopping/removing existing container (if any): $NAME"
docker stop "$NAME" >/dev/null 2>&1 || true
docker rm "$NAME" >/dev/null 2>&1 || true

echo "Starting $NAME from $IMAGE (needs GPU: --gpus all)..."
# Image default CMD is /bin/bash (exits) — run cuOpt REST explicitly (see NVIDIA cuOpt server quickstart).
docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --gpus all \
  -e CUOPT_SERVER_PORT=8000 \
  -p "127.0.0.1:${HOST_PORT}:8000" \
  "$IMAGE" \
  python3 -m cuopt_server.cuopt_service --ip 0.0.0.0 --port 8000

echo "Wait for /cuopt/health..."
for i in $(seq 1 30); do
  if curl -sf -m 2 "http://127.0.0.1:${HOST_PORT}/cuopt/health" >/dev/null; then
    echo "cuOpt health OK on http://127.0.0.1:${HOST_PORT}"
    break
  fi
  sleep 1
done

echo "nvidia-smi inside container (must succeed for solver to use GPU):"
docker exec "$NAME" nvidia-smi -L || {
  echo "FAIL: NVML inside container — check nvidia-container-toolkit and recreate with --gpus all." >&2
  exit 1
}

echo "Done. For self-hosted mode set: CUOPT_SELF_HOSTED_URL=http://127.0.0.1:${HOST_PORT}"
echo "If the GPU solver is unstable, leave that line commented and use MULTI_DC_CUOPT_CLOUD_ENABLED=true + CUOPT_API_KEY (or NVIDIA_API_KEY)."
