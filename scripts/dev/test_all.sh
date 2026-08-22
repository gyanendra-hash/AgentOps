#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

for service in rate_limiter gateway scheduler worker_pool agent_ops; do
  SERVICE_DIR="$ROOT_DIR/services/$service"
  echo "==> $service"
  python -m pip install --quiet -r "$SERVICE_DIR/requirements.txt" -r "$SERVICE_DIR/requirements-dev.txt" -e "$ROOT_DIR/libs/agentops_common"
  (cd "$SERVICE_DIR" && PYTHONPATH=. python -m pytest -v)
done
