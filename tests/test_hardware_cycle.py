from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import argparse
from pathlib import Path

from smart_bin_hardware import SmartBinHardware


PROJECT = Path("/home/smini131/smart_bin")

parser = argparse.ArgumentParser(
    description="음성 재생 후 해당 뚜껑 개방 시험"
)
parser.add_argument(
    "label",
    choices=("can", "clear_pet", "plastic", "paper"),
)
args = parser.parse_args()

print("손과 기구물이 서보 회전 범위에 없는지 확인하세요.")
input("준비됐으면 Enter를 누르세요. 취소는 Ctrl+C: ")

hardware = SmartBinHardware(
    PROJECT / "hardware_config.json"
)

try:
    hardware.handle_result(
        {
            "status": "confirmed",
            "label": args.label,
        }
    )
finally:
    hardware.cleanup()

print("[완료] 음성 + 서보 통합 시험")
