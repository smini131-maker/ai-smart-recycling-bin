from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import argparse
import json
from pathlib import Path

from smart_bin_hardware import AudioController


PROJECT = Path("/home/smini131/smart_bin")

parser = argparse.ArgumentParser()
parser.add_argument(
    "key",
    nargs="?",
    default="ready",
    choices=(
        "ready",
        "can",
        "clear_pet",
        "plastic",
        "paper",
        "other",
        "background",
        "uncertain",
        "timeout",
        "all",
    ),
)
args = parser.parse_args()

config = json.loads(
    (PROJECT / "hardware_config.json").read_text(
        encoding="utf-8"
    )
)

audio = AudioController(config["audio"])

print()
print("=== ALSA 장치 목록 ===")
print(AudioController.list_cards())
print()

keys = (
    "ready",
    "can",
    "clear_pet",
    "plastic",
    "paper",
    "other",
    "background",
    "uncertain",
    "timeout",
)

if args.key == "all":
    for key in keys:
        audio.play(key)
else:
    audio.play(args.key)

print("[완료] 오디오 시험")
