from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gpiozero import MotionSensor
from smart_bin_hardware import AudioController


GPIO_PIN = 17
COOLDOWN_SECONDS = 20.0
SENSOR_WARMUP_SECONDS = 45.0


def main() -> None:
    config_path = PROJECT_ROOT / "hardware_config.json"

    config = json.loads(
        config_path.read_text(encoding="utf-8")
    )

    audio = AudioController(config["audio"])

    pir = MotionSensor(
        GPIO_PIN,
        queue_len=5,
        sample_rate=10,
        threshold=0.6,
    )

    print("========================================")
    print("PIR 인체감지 + 음성 안내 시험")
    print("========================================")
    print(f"센서 OUT: GPIO{GPIO_PIN}, 물리 핀 11")
    print(
        f"센서 안정화: {SENSOR_WARMUP_SECONDS:.0f}초"
    )
    print("종료: Ctrl+C")
    print()

    time.sleep(SENSOR_WARMUP_SECONDS)

    print("[준비 완료] 센서 앞으로 걸어와 보세요.")

    last_announcement = -COOLDOWN_SECONDS

    try:
        while True:
            pir.wait_for_motion()

            detected_at = time.monotonic()
            elapsed = detected_at - last_announcement

            print("[감지] 사람의 움직임이 감지되었습니다.")

            if elapsed >= COOLDOWN_SECONDS:
                audio.play("ready")
                last_announcement = time.monotonic()
            else:
                remaining = COOLDOWN_SECONDS - elapsed

                print(
                    "[재생 생략] 중복 안내 방지 "
                    f"{remaining:.1f}초 남음"
                )

            print("[대기] 사람이 감지 구역을 벗어나기를 기다립니다.")

            pir.wait_for_no_motion()

            print("[해제] 움직임이 사라졌습니다.")
            time.sleep(1.0)

    finally:
        pir.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[종료] PIR 시험 종료")
