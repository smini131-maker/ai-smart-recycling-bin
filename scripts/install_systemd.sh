#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SOURCE="${PROJECT_DIR}/systemd/smart-bin.service"
SERVICE_TARGET="/etc/systemd/system/smart-bin.service"

python -m py_compile \
  "${PROJECT_DIR}/smart_bin_final.py" \
  "${PROJECT_DIR}/smart_bin_hardware.py" \
  "${PROJECT_DIR}/smart_bin_camera_ai.py" \
  "${PROJECT_DIR}/smart_bin_camera_ai_specialist.py" \
  "${PROJECT_DIR}/pet_plastic_specialist_runtime.py"

sudo cp "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
sudo systemctl daemon-reload
sudo systemctl enable --now smart-bin.service
sudo systemctl status smart-bin.service --no-pager
