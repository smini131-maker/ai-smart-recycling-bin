from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import json
from pathlib import Path

from smart_bin_hardware import (
    RECYCLABLE_LABELS,
    ServoController,
)


PROJECT = Path("/home/smini131/smart_bin")

config = json.loads(
    (PROJECT / "hardware_config.json").read_text(
        encoding="utf-8"
    )
)

servo = ServoController(config["servo"])

try:
    for label in RECYCLABLE_LABELS:
        item = config["servo"]["channels"][label]
        print()
        print("========================================")
        print(
            f"{label}: 채널 {item['channel']}, "
            f"닫힘 {item['closed_angle']}도, "
            f"열림 {item['open_angle']}도"
        )
        input(
            "이 서보를 시험하려면 Enter, "
            "전체 종료는 Ctrl+C: "
        )
        servo.cycle_lid(label)
finally:
    servo.release_all()

print("[완료] 서보 4개 순차 시험")
