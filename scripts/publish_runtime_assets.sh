#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="/home/smini131/smart_bin"
REPOSITORY="https://github.com/smini131-maker/ai-smart-recycling-bin.git"
WORK_DIR="$(mktemp -d /home/smini131/ai-smart-bin-publish.XXXXXX)"

cleanup() {
  rm -rf "${WORK_DIR}"
  sudo systemctl start smart-bin.service 2>/dev/null || true
}
trap cleanup EXIT

sudo systemctl stop smart-bin.service 2>/dev/null || true

for required in \
  "${SOURCE_DIR}/smart_bin_final.py" \
  "${SOURCE_DIR}/smart_bin_camera_ai.py" \
  "${SOURCE_DIR}/smart_bin_hardware.py" \
  "${SOURCE_DIR}/model/garbage_classifier.tflite" \
  "${SOURCE_DIR}/model/pet_plastic_classifier.tflite" \
  "${SOURCE_DIR}/audio/ready.wav" \
  "${SOURCE_DIR}/audio/other.wav" \
  "${SOURCE_DIR}/audio/remove_wait.wav"; do
  if [[ ! -s "${required}" ]]; then
    echo "[ERROR] Missing release file: ${required}" >&2
    exit 1
  fi
done

git clone "${REPOSITORY}" "${WORK_DIR}/repo"
cd "${WORK_DIR}/repo"

cp "${SOURCE_DIR}/smart_bin_final.py" .
cp "${SOURCE_DIR}/smart_bin_hardware.py" .
cp "${SOURCE_DIR}/smart_bin_camera_ai.py" .
cp "${SOURCE_DIR}/smart_bin_camera_ai_specialist.py" .
cp "${SOURCE_DIR}/pet_plastic_specialist_runtime.py" .
cp "${SOURCE_DIR}/hardware_config.json" .

rm -rf source_parts tests
mkdir -p model audio
cp "${SOURCE_DIR}/model/"*.tflite model/
cp "${SOURCE_DIR}/model/"*.txt model/
cp "${SOURCE_DIR}/model/"*.json model/
cp "${SOURCE_DIR}/audio/"*.wav audio/
cp -a "${SOURCE_DIR}/tests" ./tests

find tests -type d -name '__pycache__' -prune -exec rm -rf {} +
find tests -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -f tests/camera_test.jpg tests/python_camera_test.jpg

python scripts/preflight.py

git add -A

if git diff --cached --quiet; then
  echo "[OK] GitHub release files are already current."
else
  git commit -m "release: publish final Raspberry Pi source, models and audio"
  git push origin main
  echo "[OK] Final competition release published."
fi
