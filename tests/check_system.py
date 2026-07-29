from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import json
import shutil
import subprocess
from pathlib import Path


PROJECT = Path("/home/smini131/smart_bin")

required_files = [
    PROJECT / "smart_bin_camera_ai.py",
    PROJECT / "smart_bin_camera_ai_specialist.py",
    PROJECT / "smart_bin_final.py",
    PROJECT / "smart_bin_hardware.py",
    PROJECT / "model/garbage_classifier.tflite",
    PROJECT / "model/labels.txt",
    PROJECT / "model/pet_plastic_classifier.tflite",
    PROJECT / "model/pet_plastic_labels.txt",
    PROJECT / "hardware_config.json",
]

missing = [
    str(path)
    for path in required_files
    if not path.is_file()
]

if missing:
    raise SystemExit(
        "[실패] 필수 파일 누락:\n- "
        + "\n- ".join(missing)
    )

config = json.loads(
    (PROJECT / "hardware_config.json").read_text(
        encoding="utf-8"
    )
)

print("[통과] 필수 파일")
print(
    "[확인] 서보 채널:",
    {
        key: value["channel"]
        for key, value
        in config["servo"]["channels"].items()
    },
)

if not Path("/dev/i2c-1").exists():
    raise SystemExit(
        "[실패] /dev/i2c-1이 없습니다. I2C를 활성화하세요."
    )

print("[통과] /dev/i2c-1")

if shutil.which("i2cdetect"):
    completed = subprocess.run(
        ["i2cdetect", "-y", "1"],
        text=True,
        capture_output=True,
        check=False,
    )
    print(completed.stdout)

    if "40" not in completed.stdout:
        raise SystemExit(
            "[실패] PCA9685 주소 0x40이 보이지 않습니다."
        )

    print("[통과] PCA9685 0x40")
else:
    print("[경고] i2cdetect가 없어 주소 검사를 생략합니다.")

if shutil.which("aplay"):
    completed = subprocess.run(
        ["aplay", "-l"],
        text=True,
        capture_output=True,
        check=False,
    )
    print(completed.stdout)

    if completed.returncode != 0:
        raise SystemExit("[실패] ALSA 재생 장치가 없습니다.")

    print("[통과] ALSA 재생 장치")
else:
    raise SystemExit(
        "[실패] aplay가 없습니다. sudo apt install alsa-utils"
    )

print("[완료] 기본 시스템 검사 통과")
