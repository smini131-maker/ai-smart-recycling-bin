#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="/home/smini131/smart_bin"
PUBLISH_DIR="/home/smini131/ai-smart-recycling-bin-publish"
REPOSITORY="https://github.com/smini131-maker/ai-smart-recycling-bin.git"

restart_service() {
  sudo systemctl start smart-bin.service 2>/dev/null || true
}
trap restart_service EXIT

sudo systemctl stop smart-bin.service 2>/dev/null || true

for required in \
  "${SOURCE_DIR}/model/garbage_classifier.tflite" \
  "${SOURCE_DIR}/model/pet_plastic_classifier.tflite" \
  "${SOURCE_DIR}/audio/ready.wav" \
  "${SOURCE_DIR}/audio/other.wav" \
  "${SOURCE_DIR}/audio/remove_wait.wav"; do
  if [[ ! -s "${required}" ]]; then
    echo "[ERROR] Missing runtime asset: ${required}" >&2
    exit 1
  fi
done

rm -rf "${PUBLISH_DIR}"
git clone "${REPOSITORY}" "${PUBLISH_DIR}"
cd "${PUBLISH_DIR}"

mkdir -p model audio
cp "${SOURCE_DIR}/model/garbage_classifier.tflite" model/
cp "${SOURCE_DIR}/model/pet_plastic_classifier.tflite" model/
cp "${SOURCE_DIR}/audio/"*.wav audio/

python scripts/preflight.py

git add model/*.tflite audio/*.wav

if git diff --cached --quiet; then
  echo "[OK] Runtime assets are already current."
else
  git commit -m "assets: add final offline models and audio"
  git push origin main
  echo "[OK] Runtime assets published."
fi
