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

git clone "${REPOSITORY}" "${WORK_DIR}/repo"
cd "${WORK_DIR}/repo"

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
