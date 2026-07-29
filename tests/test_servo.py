from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import argparse
import json
from pathlib import Path

from smart_bin_hardware import ServoController


PROJECT = Path("/home/smini131/smart_bin")

parser = argparse.ArgumentParser(
    description="서보 1개 열림·닫힘 시험"
)
parser.add_argument(
    "label",
    choices=("can", "clear_pet", "plastic", "paper"),
)
args = parser.parse_args()

config_path = PROJECT / "hardware_config.json"
config = json.loads(
    config_path.read_text(encoding="utf-8")
)

item = config["servo"]["channels"][args.label]

print("================================================")
print("서보 단독 시험")
print("================================================")
print(f"분류: {args.label}")
print(f"PCA9685 채널: {item['channel']}")
print(f"닫힘 각도: {item['closed_angle']}")
print(f"열림 각도: {item['open_angle']}")
print()
print("손과 기구물이 서보 회전 범위에 없는지 확인하세요.")
input("준비됐으면 Enter를 누르세요. 취소는 Ctrl+C: ")

servo = ServoController(config["servo"])

try:
    servo.cycle_lid(args.label)
finally:
    servo.release_all()

print("[완료] 서보 단독 시험")
